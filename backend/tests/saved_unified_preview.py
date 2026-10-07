"""Read/render acceptance over a copied personal DB; never reaches a model or platform."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ['VIDEO_LEARNING_DB'] = str(ROOT / '.local/unified-saved-data/learning-copy.sqlite3')
os.environ['DEEPSEEK_API_KEY'] = 'fake-offline-render-key'

from app import main, video_service
from app.analysis_jobs import get_engine
from app.schemas import ParseResponse, VideoFormat

app = main.app


def offline_parse(url):
    with get_engine().store.connection() as db:
        row = db.execute('SELECT title,platform,duration FROM analyses WHERE url=? ORDER BY updated_at DESC LIMIT 1', (url,)).fetchone()
    if not row:
        raise RuntimeError('Offline acceptance only supports saved records')
    return ParseResponse(title=row['title'], extractor=row['platform'], duration=row['duration'],
                         formats=[VideoFormat(format_id='best', label='最佳画质（离线展示）')])


def blocked_model(*args):
    raise AssertionError('Offline acceptance must never call a model')


video_service.parse_video = offline_parse
get_engine().client_factory = blocked_model
