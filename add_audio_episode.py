"""Adds an audio-only episode (no YouTube video yet) to the feed.

    python add_audio_episode.py <id> <file.mp3> <title> <description_file>

Uploads the mp3 to a GitHub release tagged <id>, appends to episodes.json and
regenerates rss.xml. Commit and push are left to the caller.
When the video version lands in the playlist, add its YouTube ID to the
episode's 'aliases' so podcast_updater.py doesn't publish it a second time.
"""
import os, sys
from datetime import datetime
from podcast_updater import load_json, save_json, upload_to_github_release, generate_rss

ep_id, mp3, title, desc_file = sys.argv[1:5]
episodes = load_json('episodes.json', [])
if any(ep['id'] == ep_id for ep in episodes):
    sys.exit(f"{ep_id} is already in episodes.json")
url = upload_to_github_release(os.environ['GITHUB_TOKEN'], os.environ['GITHUB_REPOSITORY'], ep_id, mp3)
if not url:
    sys.exit("upload failed")
episodes.append({
    'id': ep_id,
    'title': title,
    'description': open(desc_file, encoding='utf-8').read().strip(),
    'upload_date': datetime.utcnow().strftime('%Y%m%d'),
    'duration': 0,
    'audio_url': url,
    'file_size': os.path.getsize(mp3),
    'aliases': [],
})
save_json('episodes.json', episodes)
generate_rss(load_json('podcast_info.json', {}), episodes, 'rss.xml')
print(url)
