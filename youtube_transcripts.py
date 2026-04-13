import os
import json
import time
import logging
import certifi
import ssl
import urllib.request
from datetime import datetime
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from pytube import YouTube
from urllib.error import HTTPError
import subprocess

# Load environment variables if running locally
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# AWS clients
aws_region = os.getenv("AWS_REGION", "ap-south-1")
s3_client = boto3.client('s3', region_name=aws_region)
transcribe_client = boto3.client('transcribe', region_name=aws_region)
bedrock_runtime = boto3.client('bedrock-runtime', region_name=aws_region)
dynamodb = boto3.resource('dynamodb', region_name=aws_region)

# Environment
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME")
dynamo_table = dynamodb.Table(DYNAMODB_TABLE_NAME)

def make_api_call(url):
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, context=context) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        return {}

def get_playlist_videos(api_key, playlist_id):
    videos = []
    next_page_token = ""
    while True:
        url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={playlist_id}&key={api_key}"
        if next_page_token:
            url += f"&pageToken={next_page_token}"
        response = make_api_call(url)
        items = response.get("items", [])
        for item in items:
            video_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            videos.append({"video_id": video_id, "title": title})
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return videos

def video_already_processed(video_id):
    try:
        from boto3.dynamodb.conditions import Key
        response = dynamo_table.query(
            KeyConditionExpression=Key('video_id').eq(video_id)
        )
        return response['Count'] > 0
    except ClientError as e:
        logger.error(f"DynamoDB read error for {video_id}: {e}")
        return False

def mark_video_processed(video_id, title):
    try:
        timestamp = datetime.utcnow().isoformat()
        dynamo_table.put_item(
            Item={
                'video_id': video_id,
                'timestamp': timestamp,
                'title': title,
                'processed_at': timestamp
            }
        )
        logger.info(f"Marked processed in DynamoDB: {video_id}")
    except ClientError as e:
        logger.error(f"Failed to mark video {video_id} in DynamoDB: {e}")

def upload_to_s3(file_path, s3_key):
    try:
        s3_client.upload_file(str(file_path), S3_BUCKET_NAME, s3_key)
        logger.info(f"Uploaded to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
        return f"s3://{S3_BUCKET_NAME}/{s3_key}"
    except Exception as e:
        logger.error(f"Failed to upload to S3: {e}")
        return None

def download_audio_from_youtube(video_id):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Downloading audio using yt-dlp: {url}")
        for ext in ["webm", "mp3", "m4a"]:
            try:
                os.remove(f"{video_id}.{ext}")
            except FileNotFoundError:
                pass

        # Step 1: Download audio without conversion
        download_command = [
            "yt-dlp",
            "-f", "bestaudio",
            "-o", f"{video_id}.%(ext)s",
            url
        ]
        subprocess.run(download_command, check=True)
        
        # Find the downloaded file
        downloaded_files = [f for f in os.listdir('.') if f.startswith(video_id) and not f.endswith('.mp3')]
        if not downloaded_files:
            logger.error(f"No files downloaded for {video_id}")
            return None
            
        downloaded_file = downloaded_files[0]
        
        # Step 2: Convert to mp3 using ffmpeg directly
        output_file = f"{video_id}.mp3"
        convert_command = [
            "ffmpeg",
            "-i", downloaded_file,
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            "-y",  # Overwrite output file if it exists
            output_file
        ]
        subprocess.run(convert_command, check=True)
        
        # Clean up the original file if different from output
        if downloaded_file != output_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {downloaded_file}: {e}")
            
        return output_file if os.path.exists(output_file) else None
    except subprocess.CalledProcessError as e:
        logger.error(f"Audio download/conversion failed for {video_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in download_audio_from_youtube: {e}")
        return None

def transcribe_audio(video_id, audio_path, title):
    try:
        s3_key = f"audio/{video_id}.mp3"
        upload_to_s3(audio_path, s3_key)
        job_uri = f"s3://{S3_BUCKET_NAME}/{s3_key}"
        job_name = f"transcribe_{video_id}_{int(time.time())}"

        # Define custom vocabulary for names and terms
        timestamp = int(time.time())
        custom_vocabulary_name = f"vocab_{timestamp}"
        
        # Create the vocabulary
        logger.info(f"Creating new vocabulary: {custom_vocabulary_name}")
        
        # Define your custom terms here - corrected according to AWS guidelines
        custom_terms = [
            "Capex",
            "tax-to-GDP",
            "logistics-cost",
            "global-cues",
            "fiscal-consolidation",
            "fledged",
            "firmly",
            "SIP",
            "leapfrogged",
            "folios",
            "baton",
            "able"
        ]
                
        # Create a temporary file for the vocabulary in the current directory
        vocab_file = f"{custom_vocabulary_name}.txt"
        with open(vocab_file, 'w') as f:
            for term in custom_terms:
                f.write(f"{term}\n")
        
        # Upload the vocabulary file to S3
        vocab_s3_key = f"vocabulary/{custom_vocabulary_name}.txt"
        s3_uri = upload_to_s3(vocab_file, vocab_s3_key)
        
        if not s3_uri:
            logger.error("Failed to upload vocabulary file to S3")
            raise Exception("Failed to upload vocabulary file to S3")
        
        # Create the vocabulary in AWS Transcribe
        try:
            response = transcribe_client.create_vocabulary(
                VocabularyName=custom_vocabulary_name,
                LanguageCode='en-US',
                VocabularyFileUri=s3_uri
            )
            logger.info(f"Vocabulary creation initiated: {response}")
            
            # Wait for vocabulary to be ready
            wait_count = 0
            max_wait = 24  # 2 minutes (24 * 5 seconds)
            use_custom_vocabulary = False
            
            while wait_count < max_wait:
                try:
                    response = transcribe_client.get_vocabulary(VocabularyName=custom_vocabulary_name)
                    state = response['VocabularyState']
                    logger.info(f"Vocabulary state: {state}")
                    
                    if state in ['READY', 'FAILED']:
                        if state == 'READY':
                            use_custom_vocabulary = True
                            logger.info(f"Vocabulary is ready: {custom_vocabulary_name}")
                        else:
                            logger.error(f"Vocabulary creation failed: {response.get('FailureReason', 'Unknown reason')}")
                        break
                except Exception as e:
                    logger.info(f"Waiting for vocabulary: {str(e)}")
                
                wait_count += 1
                time.sleep(5)
            
            if wait_count >= max_wait:
                logger.warning("Timed out waiting for vocabulary to be ready")
                use_custom_vocabulary = False
        
        except Exception as e:
            logger.error(f"Error creating vocabulary: {str(e)}")
            use_custom_vocabulary = False
        
        # Clean up the local vocabulary file
        try:
            os.remove(vocab_file)
        except:
            pass
        
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        
        # Start transcription job with or without the custom vocabulary
        transcription_settings = {
            'ShowSpeakerLabels': True,
            'MaxSpeakerLabels': 10  # Adjust based on your needs
        }
        
        if use_custom_vocabulary:
            transcription_settings['VocabularyName'] = custom_vocabulary_name
            logger.info(f"Using custom vocabulary: {custom_vocabulary_name}")
        else:
            logger.info("Proceeding without custom vocabulary")
        
        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': job_uri},
            MediaFormat='mp3',
            LanguageCode='en-US',
            Settings=transcription_settings,
            OutputBucketName=S3_BUCKET_NAME,
            OutputKey=f"transcriptions/{safe_title}_{video_id}_transcript.json"
        )

        while True:
            status = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
            job_status = status['TranscriptionJob']['TranscriptionJobStatus']
            if job_status in ['COMPLETED', 'FAILED']:
                break
            logger.info(f"Waiting for transcription job... ({job_status})")
            time.sleep(15)

        if job_status == 'COMPLETED':
            uri = status['TranscriptionJob']['Transcript']['TranscriptFileUri']
            logger.info(f"Transcription completed: {uri}")
            return uri
        else:
            logger.error(f"Transcription failed for {video_id}")
            return None

    except Exception as e:
        logger.error(f"Error in transcribe_audio: {e}")
        return None

def generate_bedrock_insights(video_id, transcript_text, title):
    try:
        import re

        prompt = f"""
You are a highly skilled professional YouTube video analyst. Your task is to deeply analyze the following transcript and return a detailed, structured JSON summary in the format of video insights.

Please ensure the output includes:

1. A cleanly formatted transcript (one line per speaker turn), showing speaker names or labels (e.g., "Speaker 1:", "Moderator:", etc.)
2. A detailed summary capturing the key themes, insights, and decisions made in the video.
3. A list of specific action-items clearly attributed to speakers or roles, with deadlines if mentioned.
4. A list of follow-up points, also attributed to speakers or roles where possible.

All output should be in **valid JSON** format like this:
{{
  "transcript": [
    "Speaker 1: Welcome everyone to the session.",
    "Speaker 2: Thank you. Today we will cover..."
  ],
  "summary": "A detailed overview of the key themes, issues discussed, and decisions made in the video...",
  "actionItems": [
    "Speaker 2: Prepare financial report by next Monday.",
    "Speaker 1: Follow up with the marketing team regarding the Q2 campaign."
  ],
  "followUps": [
    "Speaker 3: Clarify the budget allocation mentioned during the session.",
    "Speaker 1: Confirm attendance for the next strategy meeting."
  ]
}}

Use clear language, organize information logically, and attribute every action or follow-up to the correct speaker whenever possible.

Transcript:
{transcript_text[:10000]}
"""

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 4096,
            "temperature": 0.7,
            "top_p": 0.9
        }

        response = bedrock_runtime.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",  # Reverting to Claude 3 Sonnet which supports on-demand throughput
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )

        raw_output = response['body'].read().decode("utf-8")
        output = json.loads(raw_output)
        insights_str = output.get("content", [])[0].get("text", "").strip()

        match = re.search(r'\{[\s\S]*\}', insights_str)
        if match:
            try:
                insights_json = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("Extracted block still isn't valid JSON.")
                insights_json = {"raw_insights": insights_str}
        else:
            logger.warning("No JSON object found in Claude response.")
            insights_json = {"raw_insights": insights_str}

        insights_file = f"{video_id}_insights.json"
        with open(insights_file, "w") as f:
            json.dump(insights_json, f)

        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        s3_insights_key = f"video_insights/{safe_title}_{video_id}_insights.json"
        upload_to_s3(insights_file, s3_insights_key)
        os.remove(insights_file)

        return True

    except Exception as e:
        logger.error(f"Failed to generate insights: {e}")
        return False

def process_videos():
    api_key = os.getenv("YOUTUBE_API_KEY")
    playlist_id = os.getenv("PLAYLIST_ID")
    if not api_key or not playlist_id:
        logger.error("Missing YOUTUBE_API_KEY or PLAYLIST_ID in environment.")
        return

    videos = get_playlist_videos(api_key, playlist_id)
    for video in videos:
        video_id = video['video_id']
        title = video['title']

        if video_already_processed(video_id):
            logger.info(f"Already processed: {video_id}")
            continue

        logger.info(f"Processing: {video_id} - {title}")
        audio_path = download_audio_from_youtube(video_id)
        if not audio_path:
            continue

        transcript_uri = transcribe_audio(video_id, audio_path, title)
        if transcript_uri:
            transcript_text = json.loads(urllib.request.urlopen(transcript_uri).read())["results"]["transcripts"][0]["transcript"]
            generate_bedrock_insights(video_id, transcript_text, title)
            mark_video_processed(video_id, title)
        #os.remove(audio_path)

def lambda_handler(event, context):
    process_videos()

if __name__ == "__main__":
    process_videos()
