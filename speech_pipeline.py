import json
import os
import boto3
import requests
import yfinance as yf
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime
from io import BytesIO

load_dotenv()

TRANSCRIPTS_DIR = Path("transcripts/dir_name")
DATA_DIR = Path("data")
STYLE_FILE = DATA_DIR / "speaking_style.txt"

DATA_DIR.mkdir(exist_ok=True, parents=True)

aws_region = os.getenv("AWS_REGION", "ap-south-1") 
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Initialize AWS clients
bedrock = boto3.client(
    "bedrock-runtime", 
    region_name=aws_region,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

s3_client = boto3.client(
    "s3",
    region_name=aws_region,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

def upload_string_to_s3(content, s3_key):
    """Upload a string directly to S3 bucket without saving locally"""
    try:
        # Convert string to bytes
        bytes_content = content.encode('utf-8')
        
        # Upload bytes directly to S3
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=bytes_content,
            ContentType='text/plain'
        )
        print(f"Uploaded to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
        return f"s3://{S3_BUCKET_NAME}/{s3_key}"
    except Exception as e:
        print(f"Failed to upload to S3: {e}")
        return None

def load_combined_transcripts():
    text = ""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True, parents=True)
    
    files = list(TRANSCRIPTS_DIR.glob("*.txt"))
    if not files:
        return "This is a placeholder for transcript analysis."
    
    for file in files:
        text += file.read_text() + "\n\n"
    return text

def analyze_speaking_style(sample_text):
    prompt = f"""
    Analyze the following speech samples and describe the speaker's style in terms of tone, vocabulary, sentence structure, preferred metaphors, and overall persona.

    --- START SAMPLE ---
    {sample_text}
    --- END SAMPLE ---
    """
    try:
        response = bedrock.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800
            }),
            contentType="application/json",
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    except Exception as e:
        print(f"Error in analyze_speaking_style: {e}")
        return "Speaker has a professional, clear, and authoritative tone with financial expertise."

def get_financial_trends():
    try:
        nifty = yf.Ticker("^NSEI")
        market_data = nifty.history(period="5d").tail(1).to_dict()
        
        headlines = []
        r = requests.get("https://www.moneycontrol.com/news/business/")
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.select(".clearfix h2"):
                headlines.append(item.text.strip())
        
        return {"nifty": market_data, "headlines": headlines[:5]}
    except Exception as e:
        print(f"Error in get_financial_trends: {e}")
        return {
            "nifty": {"Open": {}, "Close": {}},
            "headlines": ["Market shows resilience amid global challenges"]
        }

def generate_speech(transcript, insights, trends, style_notes):
    prompt = f"""
    You are a Managing Director of a financial services company [COMPANY-NAME]. Write a 3-minute speech using the following:

    1. Transcript Summary: {insights['summary']}
    2. Action Points: {insights['action_items']}
    3. Trending Topics: {trends['headlines']}
    4. Market Context: Nifty latest: {trends['nifty']}
    5. Style Guide: {style_notes}

    Make it forward-looking, insightful, optimistic. Use long-term investing metaphors, if possible.
    """
    try:
        response = bedrock.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000
            }),
            contentType="application/json",
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    except Exception as e:
        print(f"Error in generate_speech: {e}")
        return "Speech generation failed. Please check your AWS credentials and try again."

def main():
    try:
        # Check if S3 bucket name is provided
        if not S3_BUCKET_NAME:
            print("Error: S3_BUCKET_NAME environment variable is not set")
            return
            
        transcript_sample = load_combined_transcripts()
        
        if STYLE_FILE.exists():
            style_notes = STYLE_FILE.read_text()
        else:
            style_notes = analyze_speaking_style(transcript_sample)
            STYLE_FILE.write_text(style_notes)

        latest_transcript = transcript_sample[-2000:] if len(transcript_sample) > 2000 else transcript_sample
        insights = {
            "summary": "Markets are showing resilience despite global uncertainty...",
            "action_items": "1. Continue SIP campaigns\n2. Engage with younger investors",
        }

        trends = get_financial_trends()

        speech = generate_speech(latest_transcript, insights, trends, style_notes)
        
        # Generate a timestamp for the filename
        timestamp = datetime.now().strftime("%Y-%m-%d")
        s3_key = f"speeches/speech_corner_{timestamp}.txt"
        
        # Upload directly to S3
        s3_uri = upload_string_to_s3(speech, s3_key)
        
        if s3_uri:
            print(f"Speech successfully uploaded to S3: {s3_uri}")
        else:
            print("Failed to upload speech to S3")
    
    except Exception as e:
        print(f"Error in main function: {e}")

if __name__ == "__main__":
    main()
