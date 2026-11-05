import os, sys, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from app.agent import Agent

logging.basicConfig(level=logging.INFO)
app = FastAPI(title='UZEX deals agent')
_agent = None


def agent():
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


class Ask(BaseModel):
    question: str


@app.post('/api/ask')
def ask(body: Ask):
    q = (body.question or '').strip()[:1000]
    if not q:
        return JSONResponse({'error': 'empty question'}, status_code=400)
    res = agent().ask(q)
    logging.info('Q=%r verified=%s no_data=%s t=%s', q, res.get('verified'), res.get('no_data'), res.get('elapsed_s'))
    return res


@app.get('/api/diag')
def diag_ep():
    from app.agent import diag
    return diag()


@app.get('/api/health')
def health():
    from app.db import get_con
    n = get_con().execute('SELECT count(*) FROM deals').fetchone()[0]
    return {'ok': True, 'deals': n}


_INDEX = os.path.join(os.path.dirname(__file__), '..', 'public', 'index.html')


@app.get('/')
def index():
    return FileResponse(_INDEX)
