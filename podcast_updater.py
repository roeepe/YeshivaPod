import os
import json
import logging
import subprocess
from datetime import datetime
import pytz
from feedgen.feed import FeedGenerator
from github import Github

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_json(filepath, default_value):
    if not os.path.exists(filepath):
        return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading {filepath}: {e}")
        return default_value

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_playlist_videos(playlist_url):
    logging.info(f"Fetching playlist info from: {playlist_url}")
    cmd = ['python', '-m', 'yt_dlp', '--flat-playlist', '--dump-json', playlist_url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"yt-dlp error: {result.stderr}")
        return []
    
    videos = []
    for line in result.stdout.strip().split('\n'):
        if line:
            videos.append(json.loads(line))
    return videos

def get_video_details(video_url):
    logging.info(f"Fetching details for {video_url}")
    cmd = ['python', '-m', 'yt_dlp', '--dump-json', video_url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"Error fetching details: {result.stderr}")
        return None
    return json.loads(result.stdout)

def download_audio(video_url, output_filename):
    logging.info(f"Downloading audio for {video_url}...")
    cmd = [
        'python', '-m', 'yt_dlp',
        '-x', 
        '--audio-format', 'mp3',
        '--audio-quality', '192K',
        '-o', output_filename,
        video_url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"Error downloading {video_url}: {result.stderr}")
        return False
    return True

def upload_to_github_release(github_token, repo_name, tag_name, file_path):
    g = Github(github_token)
    repo = g.get_repo(repo_name)
    
    # Ensure release exists
    try:
        release = repo.get_release(tag_name)
    except:
        logging.info(f"Creating release {tag_name}")
        release = repo.create_git_release(tag=tag_name, name=f"Episode {tag_name}", message="Automated podcast release")
    
    logging.info(f"Uploading {file_path} to release {tag_name}...")
    try:
        asset = release.upload_asset(file_path)
        return asset.browser_download_url
    except Exception as e:
        # Asset might already exist
        logging.warning(f"Failed to upload (might already exist): {e}")
        for asset in release.get_assets():
            if asset.name == os.path.basename(file_path):
                return asset.browser_download_url
    return None

def generate_rss(config, episodes, output_file):
    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    fg.title(config['podcast_title'])
    fg.description(config['podcast_description'])
    fg.author({'name': config['podcast_author'], 'email': config['podcast_email']})
    fg.logo(config['podcast_cover_image_url'])
    fg.subtitle(config['podcast_description'])
    fg.language('he') # Hebrew by default
    
    github_repo = os.environ.get('GITHUB_REPOSITORY', 'username/repo')
    username = github_repo.split('/')[0]
    repo = github_repo.split('/')[1] if '/' in github_repo else 'repo'
    pages_url = f"https://{username}.github.io/{repo}/"
    fg.link(href=pages_url, rel='alternate')
    
    fg.podcast.itunes_category('Education')
    fg.podcast.itunes_image(config['podcast_cover_image_url'])
    fg.podcast.itunes_explicit('no')

    # Add episodes in reverse chronological order (newest first)
    # Ensure episodes is sorted by upload_date descending, or just iterate reversed if we append newest at the end
    # Actually, FeedGenerator handles ordering, but we can just add them.
    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep['id'])
        fe.title(ep['title'])
        fe.description(ep['description'] or ep['title'])
        
        # Parse yt-dlp upload_date (YYYYMMDD) to datetime
        upload_date = datetime.strptime(ep['upload_date'], '%Y%m%d')
        # Make timezone aware (UTC)
        upload_date = upload_date.replace(tzinfo=pytz.UTC)
        fe.published(upload_date)
        
        # Enclosure
        fe.enclosure(ep['audio_url'], str(ep.get('file_size', 0)), 'audio/mpeg')

        # iTunes item image
        if ep.get('thumbnail'):
            fe.podcast.itunes_image(ep['thumbnail'])
    
    fg.rss_file(output_file, pretty=True)
    logging.info(f"RSS feed saved to {output_file}")

def main():
    config = load_json('podcast_info.json', {})
    if not config:
        logging.error("podcast_info.json not found or invalid.")
        return
        
    episodes = load_json('episodes.json', [])
    processed_ids = {ep['id'] for ep in episodes}
    
    github_token = os.environ.get('GITHUB_TOKEN')
    github_repo = os.environ.get('GITHUB_REPOSITORY')
    
    if not github_token or not github_repo:
        logging.warning("GITHUB_TOKEN or GITHUB_REPOSITORY not set. Audio upload to releases will be skipped.")
    
    videos = get_playlist_videos(config['youtube_playlist_url'])
    new_episodes_found = False
    
    for video in videos:
        vid = video['id']
        if vid in processed_ids:
            continue
            
        logging.info(f"New video found: {video.get('title', vid)}")
        details = get_video_details(f"https://www.youtube.com/watch?v={vid}")
        if not details:
            continue
            
        mp3_filename = f"{vid}.mp3"
        success = download_audio(details['webpage_url'], mp3_filename)
        
        if success:
            file_size = os.path.getsize(mp3_filename)
            audio_url = ""
            
            if github_token and github_repo:
                audio_url = upload_to_github_release(github_token, github_repo, vid, mp3_filename)
                
            if audio_url:
                ep_data = {
                    'id': vid,
                    'title': details.get('title', 'Unknown Title'),
                    'description': details.get('description', ''),
                    'upload_date': datetime.utcnow().strftime('%Y%m%d'),
                    'duration': details.get('duration', 0),
                    'audio_url': audio_url,
                    'file_size': file_size,
                    'thumbnail': f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                }
                episodes.append(ep_data)
                save_json('episodes.json', episodes)
                processed_ids.add(vid)
                new_episodes_found = True
                
                # Cleanup mp3 locally after upload
                os.remove(mp3_filename)
            else:
                logging.error("Failed to get audio URL from GitHub releases. Not saving to episodes.json.")
        
    if new_episodes_found or not os.path.exists('rss.xml'):
        generate_rss(config, episodes, 'rss.xml')
    else:
        logging.info("No new episodes to process.")

if __name__ == '__main__':
    main()
