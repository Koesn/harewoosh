# HareWoosh
A one-click to transcribe, summarize, and create outline of large speech audio using [Insanely Fast Whisper](https://github.com/Vaibhavs10/insanely-fast-whisper).

## Description
Harewoosh is a limitless transcriber web UI. It designed to transcribe huge speech/audio file without worries. Uploading, transcribing, and summarizing large video/audio file are no longer a hassle. It's not like public endpoint which mostly limited to 25 MB of file to transcribe. HareWoosh is simply no limit.  
  
HareWoosh designed to quickly capture ideas of a speech, it will create summary and outline of the transcribed file. Leveraging Insanely Fast Whisper with whisper-large-v3-turbo, the process is very fast.  

![Whoosh](https://static.promediateknologi.id/crop/30x1157:1020x1691/0x0/webp/photo/p2/69/2024/08/10/Screenshot_20240810_163740_Instagram-3532592484.jpg)

## Screenshots
![Uploading large file](https://i.ibb.co.com/HfJqdJFq/Tangkapan-Layar-2025-03-03-pukul-08-32-58.png)
![Transcribing process](https://i.ibb.co.com/3yw5z0BY/Tangkapan-Layar-2025-03-03-pukul-08-34-17.png)
![Finished process](https://i.ibb.co.com/zh57yQVh/Tangkapan-Layar-2025-03-03-pukul-08-38-28.png)

## Getting Started
1. Install [Insanely Fast Whisper](https://github.com/Vaibhavs10/insanely-fast-whisper) as described on it's repo.
2. Clone this repo: `git clone https://github.com/Koesn/harewoosh`.
3. Run HareWoosh: `uvicorn main:app --host 0.0.0.0 --port 8001 --reload`.

I haven't yet documented it's requirements, so for now you can add it manually using `pip install <module>`.
