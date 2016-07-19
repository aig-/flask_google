import os
import logging
import random
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from logging.handlers import RotatingFileHandler
import time
from werkzeug import secure_filename
from celery import Celery
from bs4 import BeautifulSoup
import urllib, urllib2

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'tmp')
LOG_FILE = os.path.join(BASE_DIR, 'logs/flask_google1.log')
ALLOWED_EXTENSIONS = set(['txt'])

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

handler = RotatingFileHandler(LOG_FILE, maxBytes=10000, backupCount=7)
handler.setLevel(logging.DEBUG)
app.logger.addHandler(handler)

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)


def allowed_file(filename):
    """

	:rtype : object
	"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


def delete_prev_files():
    for f in os.listdir(app.config['UPLOAD_FOLDER']):
        if allowed_file(f):
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], f))


@app.route("/", methods=['GET', 'POST'])
def index():
    if request.method == 'POST':  # and request.form['submit'] == 'Upload':
        file = request.files['file']
        if file and allowed_file(file.filename):
            delete_prev_files()
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return redirect(url_for('index'))
    return render_template('index.html', files=[f for f in os.listdir(app.config['UPLOAD_FOLDER']) if allowed_file(f)])


@app.route('/search', methods=['POST'])
def search():
    try :
        filename = request.form.get('filename', None)
        tasks = []
        if filename:
            with open(os.path.join(app.config['UPLOAD_FOLDER'], filename)) as f:
                query_lines = f.readlines()
            for q in query_lines:
                task = search_task.apply_async([q.strip()])
                tasks.append(task)
            if len(tasks) :
                return jsonify({'taskstatus_urls':[url_for('taskstatus', task_id=task.id) for task in tasks]}), 202#, {'Location': [url_for('taskstatus', task_id=task.id) for task in tasks]}
    except Exception as e:
        app.logger.exception("Exception in search")
        return jsonify({
            'state': 'FAILURE',
            'status': e.message
        })
    return jsonify({
            'state': 'FAILURE',
            'status': 'filename empty !'
        })


@app.route('/status/<task_id>')
def taskstatus(task_id):
    task = search_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)


@celery.task(bind=True)
def search_task(self, query):
    links = google_scrape(query)
    app.logger.info("query={} # res={}".format(query,links))
    return {'status': 'Search [{}] finished'.format(query), 'result': links}


def google_scrape(query):
    address = "https://www.google.com/search?q=%s&num=100&hl=en&num=1" % (urllib.quote_plus(query))
    request = urllib2.Request(address, None, {
        'User-Agent': 'Mosilla/5.0 (Macintosh; Intel Mac OS X 10_7_4) AppleWebKit/536.11 (KHTML, like Gecko) Chrome/20.0.1132.57 Safari/536.11'})
    urlfile = urllib2.urlopen(request)
    page = urlfile.read()
    soup = BeautifulSoup(page, "html.parser")

    links = []

    for li in soup.findAll('div', attrs={'class': 'g'}):
        sLink = li.find('a')
        sSpan = li.find('span', attrs={'class': 'st'})
        links.append("{}<br/>{}".format(sLink,sSpan if sSpan else "No description"))

    return (links[0] if len(links)>0 else "No search results")


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
