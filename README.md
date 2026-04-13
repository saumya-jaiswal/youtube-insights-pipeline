# YouTube Insights & Speech Generation Pipeline

An end-to-end Python pipeline that automatically fetches videos from a YouTube playlist, transcribes them using AWS Transcribe, generates structured insights using AWS Bedrock (Claude 3 Sonnet), and stores everything in AWS S3 and DynamoDB. Includes a speech generation module that analyses a speaker's communication style from transcripts and generates contextually relevant speeches using real-time financial data.

## Problem Statement

Employees at a financial services firm couldn't access YouTube due to company security restrictions, yet needed to stay updated with the Managing Director's video content. Watching full 1-hour videos was impractical. This pipeline automates the entire process — fetching, transcribing and summarising videos into 5-minute insight reports — and extends further to auto-generate speeches in the MD's style.

## Architecture
YouTube Playlist
↓
YouTube Data API v3 (fetch video list)
↓
yt-dlp + ffmpeg (download & convert audio)
↓
AWS S3 (store audio files)
↓
AWS Transcribe (transcribe audio with custom vocabulary)
↓
AWS Bedrock — Claude 3 Sonnet (generate structured insights)
↓
AWS S3 (store transcripts & insights) + DynamoDB (track processed videos)
↓
Speech Pipeline (analyse speaking style → generate speeches using real-time market data)

## Features

- Fetches all videos from a YouTube playlist automatically
- Downloads and converts audio using yt-dlp and ffmpeg
- Transcribes audio using AWS Transcribe with custom domain vocabulary for improved accuracy
- Avoids reprocessing using DynamoDB to track processed video IDs
- Generates structured JSON insights (summary, action items, follow-ups) using Claude 3 Sonnet via AWS Bedrock
- Analyses speaker communication style from transcripts
- Generates contextually relevant speeches using real-time Nifty market data and financial news headlines

## Project Structure
youtube-insights-pipeline/
├── youtube_transcripts.py    ← main pipeline: fetch, transcribe, generate insights
├── speech_pipeline.py        ← speaking style analysis and speech generation
├── requirements.txt          ← Python dependencies
├── .env.example              ← environment variables template
└── README.md

## Setup

### Prerequisites

Install ffmpeg before running:
- **Mac:** `brew install ffmpeg`
- **Windows:** Download from https://ffmpeg.org/download.html and add to PATH
- **Linux:** `sudo apt install ffmpeg`

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key from Google Cloud Console |
| `PLAYLIST_ID` | YouTube playlist ID to process |
| `S3_BUCKET_NAME` | AWS S3 bucket name for storing files |
| `DYNAMODB_TABLE_NAME` | DynamoDB table name for tracking processed videos |
| `AWS_REGION` | AWS region (e.g. ap-south-1) |
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |

### AWS IAM Permissions Required

Your IAM user needs the following policies:
- `AmazonS3FullAccess`
- `AmazonDynamoDBFullAccess`
- `AmazonTranscribeFullAccess`
- `AmazonBedrockFullAccess`

### Running

```bash
# Run the main pipeline
python youtube_transcripts.py

# Run the speech generation pipeline
python speech_pipeline.py
```

## How It Works

### youtube_transcripts.py

1. Fetches all videos from the configured YouTube playlist
2. Checks DynamoDB to skip already processed videos
3. Downloads audio using yt-dlp and converts to MP3 via ffmpeg
4. Uploads audio to S3 and starts an AWS Transcribe job with custom vocabulary
5. Once transcription completes, sends transcript to Claude 3 Sonnet via Bedrock
6. Saves structured JSON insights (transcript, summary, action items, follow-ups) back to S3
7. Marks video as processed in DynamoDB

### speech_pipeline.py

1. Loads all transcripts from local storage
2. Analyses the speaker's communication style using Claude 3 Sonnet
3. Fetches real-time Nifty market data and financial news headlines
4. Generates a contextually relevant speech in the speaker's style
5. Uploads the generated speech directly to S3

## Notes

- This project requires active AWS credentials and a YouTube Data API key to run
- YouTube blocks API requests from cloud services (Lambda, EC2), so the pipeline is designed to run locally
- The custom vocabulary in AWS Transcribe significantly improves accuracy for domain-specific financial terminology

## Tech Stack

Python, AWS S3, AWS Transcribe, AWS Bedrock, AWS DynamoDB, Claude 3 Sonnet, YouTube Data API v3, yt-dlp, ffmpeg, yfinance, BeautifulSoup
