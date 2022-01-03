#-------------------------------------------------------------------------------
#
# Name:        Quizlet plugin for Anki 2.0
# Purpose:     Import decks from Quizlet into Anki 2.0
# Author:
#  - Original: (c) Rolph Recto 2012, last updated 12/06/2012
#              https://github.com/rolph-recto/Anki-Quizlet
#  - Also:     Contributions from https://ankiweb.net/shared/info/1236400902
#  - Current:  JDMaybeMD
# Created:     04/07/2017
#
# Changlog:    Inital release
#               - Rolph's plugin functionality was broken, so...
#               - removed search tables and associated functions to KISS
#               - reused the original API key, dunno if that's OK
#               - replaced with just one box, for a quizlet URL
#               - added basic error handling for dummies
#
#               Update 04/09/2017
#               - modified to now take a full Quizlet url for ease of use
#               - provide feedback if trying to download a private deck
#               - return RFC 2616 response codes when error handling
#               - don't make a new card type every time a new deck imported
#               - better code documentation so people can modify it
#
#               Update 01/31/2018
#               - get original quality images instead of mobile version
#
#               Update 09/12/2018
#               - updated to Anki 2.1 (by kelciour)
#
#               Update 04/02/2020
#               - download a set without API key since it's no longer working (by kelciour)
#
#               Update 19/02/2020
#               - download private or password-protected sets using cookies (by kelciour)
#
#               Update 25/02/2020
#               - make it work again by adding the User-Agent header (by kelciour)
#
#               Update 14/04/2020
#               - try to get title from HTML a bit differently (by kelciour)
#
#               Update 29/04/2020
#               - suggest to disable VPN if a set is blocked by a captcha (by kelciour)
#-------------------------------------------------------------------------------
#!/usr/bin/env python

__window = None

import sys, math, time, urllib.parse, json, re
from operator import itemgetter

# Anki
from aqt import mw
from aqt.qt import *
from aqt.utils import showText

import requests
import shutil

requests.packages.urllib3.disable_warnings()

headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.67 Safari/537.36"
}

# add custom model if needed
def addCustomModel(name, col):

    # create custom model for imported deck
    mm = col.models
    existing = mm.byName("Basic Quizlet Extended")
    if existing:
        return existing
    m = mm.new("Basic Quizlet Extended")

    # add fields
    mm.addField(m, mm.newField("FrontText"))
    mm.addField(m, mm.newField("FrontAudio"))
    mm.addField(m, mm.newField("BackText"))
    mm.addField(m, mm.newField("BackAudio"))
    mm.addField(m, mm.newField("Image"))
    mm.addField(m, mm.newField("Add Reverse"))

    # add cards
    t = mm.newTemplate("Normal")


    # front
    t['qfmt'] = "{{FrontText}}\n<br><br>\n{{FrontAudio}}"
    t['afmt'] = "{{FrontText}}\n<hr id=answer>\n{{BackText}}\n<br><br>\n{{Image}}\n<br><br>\n{{BackAudio}}"
    mm.addTemplate(m, t)


    # back
    t = mm.newTemplate("Reverse")
    t['qfmt'] = "{{#Add Reverse}}{{BackText}}\n<br><br>\n{{BackAudio}}{{/Add Reverse}}"
    t['afmt'] = "{{BackText}}\n<hr id=answer>\n{{FrontText}}\n<br><br>\n{{FrontAudio}}\n{{Image}}"
    mm.addTemplate(m, t)

    mm.add(m)
    return m

# throw up a window with some info (used for testing)
def debug(message):
    QMessageBox.information(QWidget(), "Message", message)

def getText(d, text=''):
    if d is None:
        return text
    if d['type'] == 'text':
        text = d['text']
        if 'marks' in d:
            for m in d['marks']:
                if m['type'] in ['b', 'i', 'u']:
                    text = '<{0}>{1}</{0}>'.format(m['type'], text)
                if 'attrs' in m:
                    attrs = " ".join(['{}="{}"'.format(k, v) for k, v in m['attrs'].items()])
                    text = '<span {}>{}</span>'.format(attrs, text)
        return text
    text = ''.join([getText(c) for c in d['content']]) if d.get('content') else ''
    if d['type'] == 'paragraph':
        text = '<div>{}</div>'.format(text)
    return text

def ankify(text):
    text = text.replace('\n','<br>')
    text = text.replace('class="bgY"', 'style="background-color:#fff4e5;"')
    text = text.replace('class="bgB"', 'style="background-color:#cde7fa;"')
    text = text.replace('class="bgP"', 'style="background-color:#fde8ff;"')
    return text

class QuizletWindow(QWidget):

    # used to access Quizlet API
    __APIKEY = "ke9tZw8YM6"

    # main window of Quizlet plugin
    def __init__(self):
        super(QuizletWindow, self).__init__()

        self.results = None
        self.thread = None

        self.initGUI()

    # create GUI skeleton
    def initGUI(self):

        self.box_top = QVBoxLayout()
        self.box_upper = QHBoxLayout()

        # left side
        self.box_left = QVBoxLayout()

        # quizlet url field
        self.box_name = QHBoxLayout()
        self.label_url = QLabel("Quizlet URL:")
        self.text_url = QLineEdit("",self)
        self.text_url.setMinimumWidth(300)
        self.box_name.addWidget(self.label_url)
        self.box_name.addWidget(self.text_url)


        self.box_download_audio = QHBoxLayout()
        self.value_download_audio = QCheckBox("",self)
        self.value_download_audio.toggle();
        self.value_download_audio.setMinimumWidth(300)
        self.label_download_audio = QLabel("Download audio:")
        self.box_download_audio.addWidget(self.label_download_audio)
        self.box_download_audio.addWidget(self.value_download_audio)

        self.box_start_phrase = QHBoxLayout()
        self.value_start_phrase = QLineEdit("",self)
        self.value_start_phrase.setMinimumWidth(300)
        self.value_start_phrase.setPlaceholderText('Start from this phrase. Can be empty')
        self.label_start_phrase = QLabel("Start Phrase:")
        self.box_start_phrase.addWidget(self.label_start_phrase)
        self.box_start_phrase.addWidget(self.value_start_phrase)

        self.box_stop_phrase = QHBoxLayout()
        self.value_stop_phrase = QLineEdit("",self)
        self.value_stop_phrase.setMinimumWidth(300)
        self.value_stop_phrase.setPlaceholderText('Stop after this phrase. Can be empty')
        self.label_stop_phrase = QLabel("Stop Phrase:")
        self.box_stop_phrase.addWidget(self.label_stop_phrase)
        self.box_stop_phrase.addWidget(self.value_stop_phrase)

        # add layouts to left
        self.box_left.addLayout(self.box_name)
        self.box_left.addLayout(self.box_download_audio)
        self.box_left.addLayout(self.box_start_phrase)
        self.box_left.addLayout(self.box_stop_phrase)

        # right side
        self.box_right = QVBoxLayout()

        # code (import set) button
        self.box_code = QHBoxLayout()
        self.button_code = QPushButton("Import Deck", self)
        self.box_code.addStretch(1)
        self.box_code.addWidget(self.button_code)
        self.button_code.clicked.connect(self.onCode)

        # add layouts to right
        self.box_right.addLayout(self.box_code)

        # add left and right layouts to upper
        self.box_upper.addLayout(self.box_left)
        self.box_upper.addSpacing(20)
        self.box_upper.addLayout(self.box_right)

        # results label
        self.label_results = QLabel("\r\n<i>Example: https://quizlet.com/150875612/usmle-flash-cards/</i>")

        # add all widgets to top layout
        self.box_top.addLayout(self.box_upper)
        self.box_top.addWidget(self.label_results)
        self.box_top.addStretch(1)
        self.setLayout(self.box_top)

        # go, baby go!
        self.setMinimumWidth(500)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.setWindowTitle("Improved Quizlet to Anki Importer")
        self.show()

    def onCode(self):

        # grab url input
        url = self.text_url.text()

        # voodoo needed for some error handling
        if urllib.parse.urlparse(url).scheme:
            urlDomain = urllib.parse.urlparse(url).netloc
            urlPath = urllib.parse.urlparse(url).path
        else:
            urlDomain = urllib.parse.urlparse("https://"+url).netloc
            urlPath = urllib.parse.urlparse("https://"+url).path

        # validate quizlet URL
        if url == "":
            self.label_results.setText("Oops! You forgot the deck URL :(")
            return
        elif not "quizlet.com" in urlDomain:
            self.label_results.setText("Oops! That's not a Quizlet URL :(")
            return

        # validate and set Quizlet deck ID
        quizletDeckID = urlPath.strip("/")
        if quizletDeckID == "":
            self.label_results.setText("Oops! Please use the full deck URL :(")
            return
        elif not bool(re.search(r'\d', quizletDeckID)):
            self.label_results.setText("Oops! No deck ID found in path <i>{0}</i> :(".format(quizletDeckID))
            return
        else: # get first set of digits from url path
            quizletDeckID = re.search(r"\d+", quizletDeckID).group(0)

        # and aaawaaaay we go...
        self.label_results.setText("Connecting to Quizlet...")

        # build URL
        deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)

        # download the data!
        self.thread = QuizletDownloader(self, deck_url)
        self.thread.start()

        while not self.thread.isFinished():
            mw.app.processEvents()
            self.thread.wait(50)

        # error fetching data
        if self.thread.error:
            if self.thread.errorCode == 403:
                if self.thread.errorCaptcha:
                    self.label_results.setText("Sorry, it's behind a captcha. Try to disable VPN")
                else:
                    self.label_results.setText("Sorry, this is a private deck :(")
            elif self.thread.errorCode == 404:
                self.label_results.setText("Can't find a deck with the ID <i>{0}</i>".format(quizletDeckID))
            else:
                self.label_results.setText("Unknown Error")
                # errorMessage = json.loads(self.thread.errorMessage)
                # showText(json.dumps(errorMessage, indent=4))
                showText(self.thread.errorMessage)
        else: # everything went through, let's roll!
            deck = self.thread.results
            # self.label_results.setText(("Importing deck {0} by {1}...".format(deck["title"], deck["created_by"])))
            self.label_results.setText(("Importing deck {0}...".format(deck["title"])))
            self.createDeck(deck)
            # self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards by <i>{2}</i>)".format(deck["title"], deck["term_count"], deck["created_by"])))
            self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards)".format(deck["title"], deck["term_count"])))

        # self.thread.terminate()
        self.thread = None

    def createDeck(self, result):
        # create new deck and custom model
        if "set" in result:
            name = result['set']['title']
        elif "studyable" in result:
            name = result['studyable']['title']
        else:
            name = result['title']

        items= result['items']
        progress = 0

        result['term_count'] = len(items)

        deck = mw.col.decks.get(mw.col.decks.id(name))
        model = addCustomModel(name, mw.col)

        # assign custom model to new deck
        mw.col.decks.select(deck["id"])
        mw.col.decks.save(deck)

        # assign new deck to custom model
        mw.col.models.setCurrent(model)
        model["did"] = deck["id"]
        mw.col.models.save(model)

        startProcess = False
        stopProcess = False
        startPhrase = self.value_start_phrase.text()
        stopPhrase = self.value_stop_phrase.text()
        downloadAudio = self.value_download_audio.isChecked()

        for item in items:
            if "".__eq__(startPhrase) or startPhrase == item["term"] or startPhrase == item["definition"]:
                startProcess = True

            if not stopProcess and startProcess:
                note = mw.col.newNote()
                note["FrontText"] = item["term"]
                note["BackText"] = item["definition"]
                note["FrontText"] = ankify(note["FrontText"])
                note["BackText"] = ankify(note["BackText"])

                if item.get('termAudio') and downloadAudio:
                    file_name = self.fileDownloader(self.getAudioUrl(item['termAudio']), str(item["id"]) + "-front.mp3")
                    note["FrontAudio"] = "[sound:" + file_name +"]"

                if item.get('definitionAudio') and downloadAudio:
                    file_name = self.fileDownloader(self.getAudioUrl(item["definitionAudio"]), str(item["id"]) + "-back.mp3")
                    note["BackAudio"] = "[sound:" + file_name +"]"

                if item.get('imageUrl'):
                    file_name = self.fileDownloader(item["imageUrl"])
                    note["Image"] += '<div><img src="{0}"></div>'.format(file_name)

                    mw.app.processEvents()
                mw.col.addNote(note)

                progress += 1
                self.label_results.setText(("Imported {0}/{1}".format(progress, len(items))))
                mw.app.processEvents()

            if not "".__eq__(stopPhrase) and (stopPhrase == item["term"] or stopPhrase == item["definition"]):
                stopProcess = True

        mw.col.reset()
        mw.reset()

    def getAudioUrl (self, word_audio):
        return word_audio if word_audio.startswith('http') else "https://quizlet.com/{0}".format(word_audio)

    # download the images
    def fileDownloader(self, url, suffix=''):
        url = url.replace('_m', '')
        file_name = "quizlet-" + suffix if suffix else  "quizlet-" + url.split('/')[-1]
        # get original, non-mobile version of images
        r = requests.get(url, stream=True, verify=False, headers=headers)
        if r.status_code == 200:
            with open(file_name, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
        return file_name

def parseTextItem(item):
    return getText(item["text"]["richText"], item["text"]["plainText"])

def parseAudioUrlItem(item):
    return item["text"]["ttsUrl"]

def mapItems(jsonData):
    studiableItems, studiableCardSides, studiableMediaConnections = itemgetter('studiableItems', 'studiableCardSides','studiableMediaConnections')(jsonData['studiableData'])
    result = []

    for studiableItem in studiableItems:
        term_id = next((x for x in studiableCardSides if (x["studiableItemId"] == studiableItem["id"] and x["label"] == 'word') ), None)
        definition_id = next((x for x in studiableCardSides if (x["studiableItemId"] == studiableItem["id"] and x["label"] == 'definition') ), None)

        term = next((x for x in studiableMediaConnections if (x["connectionModelId"] == term_id["id"]) ), None)
        definition = next((x for x in studiableMediaConnections if (x["connectionModelId"] == definition_id["id"]) ), None)

        image = next((x for x in studiableMediaConnections if (x["connectionModelId"] == definition_id["id"] and x["mediaType"] == 2)), None)
        definition_audio = parseAudioUrlItem(definition)

        if not definition_audio:
            definition_audio = next((x for x in studiableMediaConnections if (x["connectionModelId"] == definition_id["id"] and x["mediaType"] == 4)), None)
            definition_audio = definition_audio["audio"]["url"] if definition_audio else None

        result.append({
            "id": studiableItem["id"],
            "term": parseTextItem(term),
            "termAudio": parseAudioUrlItem(term),
            "definition": parseTextItem(definition),
            "definitionAudio": definition_audio,
            "imageUrl": image["image"].get("url") if image else None
        })

    return result

class QuizletDownloader(QThread):

    # thread that downloads results from the Quizlet API
    def __init__(self, window, url):
        super(QuizletDownloader, self).__init__()
        self.window = window

        self.url = url
        self.results = None

        self.error = False
        self.errorCode = None
        self.errorCaptcha = False
        self.errorReason = None
        self.errorMessage = None

    def run(self):
        r = None
        try:
            config = mw.addonManager.getConfig(__name__)

            cookies = {}
            if config["qlts"]:
                cookies = { "qlts": config["qlts"] }
            elif config["cookies"]:
                from http.cookies import SimpleCookie
                C = SimpleCookie()
                C.load(config["cookies"])
                cookies = { key: morsel.value for key, morsel in C.items() }

            r = requests.get(self.url, verify=False, headers=headers, cookies=cookies)
            r.raise_for_status()

            regex = re.escape('window.Quizlet["setPasswordData"]')

            if re.search(regex, r.text):
                self.error = True
                self.errorCode = 403
                return

            regex = re.escape('window.Quizlet["setPageData"] = ')
            regex += r'(.+?)'
            regex += re.escape('; QLoad("Quizlet.setPageData");')
            m = re.search(regex, r.text)

            if not m:
                regex = re.escape('window.Quizlet["assistantModeData"] = ')
                regex += r'(.+?)'
                regex += re.escape('; QLoad("Quizlet.assistantModeData");')
                m = re.search(regex, r.text)

            if not m:
                regex = re.escape('window.Quizlet["cardsModeData"] = ')
                regex += r'(.+?)'
                regex += re.escape('; QLoad("Quizlet.cardsModeData");')
                m = re.search(regex, r.text)

            data = m.group(1).strip()
            self.results = {}
            self.results['items'] = mapItems(json.loads(data))

            title = os.path.basename(self.url.strip()) or "Quizlet Flashcards"
            m = re.search(r'<title>(.+?)</title>', r.text)
            if m:
                title = m.group(1)
                title = re.sub(r' \| Quizlet$', '', title)
                title = re.sub(r'^Flashcards ', '', title)
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
            self.results['title'] = title
        except requests.HTTPError as e:
            self.error = True
            self.errorCode = e.response.status_code
            self.errorMessage = e.response.text
            if "CF-Chl-Bypass" in e.response.headers:
                self.errorCaptcha = True
        except ValueError as e:
            self.error = True
            self.errorMessage = "Invalid json: {0}".format(e)
        except Exception as e:
            self.error = True
            self.errorMessage = "{}\n-----------------\n{}".format(e, r.text)
        # yep, we got it

# plugin was called from Anki
def runQuizletPlugin():
    global __window
    __window = QuizletWindow()

# create menu item in Anki
action = QAction("Import from Quizlet", mw)
action.triggered.connect(runQuizletPlugin)
mw.form.menuTools.addAction(action)
