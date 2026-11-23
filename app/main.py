import os
from pathlib import Path

from flask import Flask

from .errors import TrialError
from .routes import api
from .workbench import station


def create_app(archive=None, ledger=None):
    app = Flask(__name__)
    archive = Path(archive or os.getenv('PECTIN_ARCHIVE', 'instance/trials'))
    app.config.update(ARCHIVE=archive, LEDGER=Path(ledger or os.getenv('PECTIN_LEDGER', archive / 'issues')),
                      MAX_CONTENT_LENGTH=1_700_000)
    app.register_blueprint(api)
    app.register_blueprint(station)

    @app.errorhandler(TrialError)
    def invalid(error):
        return {'code': error.code}, error.status

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    return app
