"""Exercise Source-owned acquisition and real FFmpeg processing without upstream credentials."""
import json
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

import yt_dlp
from yt_dlp.downloader.http import HttpFD
from vodloft_source_media import download


def verify():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg and ffprobe are required')
    with tempfile.TemporaryDirectory(prefix='vodloft-media-check-') as folder:
        root = Path(folder)
        fixture = root / 'upstream.wav'
        with wave.open(str(fixture), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(b''.join(struct.pack('<h', round(12000 * math.sin(2 * math.pi * 440 * index / 16000)))
                for index in range(16000)))
        info = {'id': 'fixture-audio', 'title': 'Upstream title', 'description': 'Upstream description',
            'url': 'https://example.com/fixture.wav', 'webpage_url': 'https://example.com/watch/fixture',
            'ext': 'wav', 'protocol': 'https', 'format_id': 'fixture', 'vcodec': 'none', 'acodec': 'pcm_s16le',
            'language': 'en', 'duration': 1, 'chapters': [{'title': 'Opening', 'start_time': 0, 'end_time': 1}]}
        def transport(self, filename, metadata):
            shutil.copyfile(fixture, filename)
            return True
        # Only the extraction and network transport are fixtures. Normal yt-dlp
        # selection, Source metadata, extraction, tagging, and FFmpeg all run.
        with patch.object(yt_dlp.YoutubeDL, 'extract_info', return_value=info), patch.object(HttpFD, 'real_download', transport):
            result = download(info['webpage_url'], str(root / 'staging'), 'format_audio_only',
                representation={'container': 'm4a', 'audio_codec': 'aac', 'languages': ['en'],
                    'language_fallback': False, 'chapters': True, 'embed_metadata': True},
                metadata={'title': 'VodLoft edited title', 'description': 'VodLoft edited description'})
        output = root / 'staging' / result.filename
        assert output.suffix == '.m4a' and result.size == output.stat().st_size
        probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
            '-show_chapters', '-of', 'json', str(output)], text=True, capture_output=True, check=True).stdout)
        assert probe['streams'][0]['codec_name'] == 'aac'
        assert probe['format']['tags']['title'] == 'VodLoft edited title'
        tags = probe['format']['tags']
        assert tags.get('description') == 'VodLoft edited description' or tags.get('comment') == 'VodLoft edited description'
        assert probe['chapters'][0]['tags']['title'] == 'Opening'
    print('Source media acceptance passed: real AAC/M4A output, edited metadata, and chapters.')


if __name__ == '__main__':
    verify()
