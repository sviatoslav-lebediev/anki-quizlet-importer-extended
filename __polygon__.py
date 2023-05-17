import re
import json


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.67 Safari/537.36"
}


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
                    attrs = " ".join(['{}="{}"'.format(k, v)
                                     for k, v in m['attrs'].items()])
                    text = '<span {}>{}</span>'.format(attrs, text)
        return text
    text = ''.join([getText(c) for c in d['content']]
                   ) if d.get('content') else ''
    if d['type'] == 'paragraph':
        text = '<div>{}</div>'.format(text)
    return text


def ankify(text):
    text = text.replace('\n', '<br>')
    text = text.replace('class="bgY"', 'style="background-color:#fff4e5;"')
    text = text.replace('class="bgB"', 'style="background-color:#cde7fa;"')
    text = text.replace('class="bgP"', 'style="background-color:#fde8ff;"')
    return text


def parseTextItem(item):
    return getText(item["text"]["richText"], item["text"]["plainText"])


def parseAudioUrlItem(item):
    return item["text"]["ttsUrl"]


def mapItems(jsonData):
    studiableDocumentData = jsonData['studiableDocumentData']
    setIdToDiagramImage = studiableDocumentData.get(
        'setIdToDiagramImage', None)
    studiableItems = studiableDocumentData.get(
        'studiableItems', studiableDocumentData.get('studiableItem'))
    result = []
    image = None
    term_audio = None
    definition_audio = None

    for studiableItem in studiableItems:
        image = None
        term_audio = None
        definition_audio = None

        for side in studiableItem["cardSides"]:
            if (side["label"] == "word"):
                for media in side["media"]:
                    if media["type"] == 4:
                        term_audio = media["url"]

                    if media["type"] == 1:
                        term = media["plainText"]

                        if media["ttsUrl"] and term_audio == None:
                            term_audio = media["ttsUrl"]

            if (side["label"] == "definition"):
                for media in side["media"]:
                    if media["type"] == 4:
                        definition_audio = media["url"]

                    if media["type"] == 1:
                        definition = media["plainText"]

                        if media["ttsUrl"] and definition_audio == None:
                            definition_audio = media["ttsUrl"]

                    if (media["type"] == 2) and (image == None):
                        image = media["url"]

            if (side["label"] == "location"):
                for media in side["media"]:
                    if (media["type"] == 5) and (image == None):
                        image = setIdToDiagramImage[str(
                            studiableItem["studiableContainerId"])]["url"]

    # "studiableDocumentData": {
    #     "setIdToDiagramImage": {
    #         "363366586": {
    #             "code": "FptcNGFe5ZbXby45",
    #             "height": 750,
    #             "url": "https://o.quizlet.com/eQYBl8GJvHXbLeXJ3nd0Zw_b.png",
    #             "width": 999
    #         }
    #     },
            # if term == 'Where is Paragonimus westermani found?':
            #         print ("yep", term_audio)
            #         print ({
            #             "id": studiableItem["id"],
            #             "term": term,
            #             "termAudio": term_audio,
            #             "definition": definition,
            #             "definitionAudio": definition_audio,
            #             "imageUrl": image
            #             })
            #         quit()

        result.append({
            "id": studiableItem["id"],
            "term": term,
            "termAudio": term_audio,
            "definition": definition,
            "definitionAudio": definition_audio,
            "imageUrl": image
        })

    return result


def getUnofficialApiData():
    quizletDeckID = 363366586
    deckUrl = 'https://quizlet.com/webapi/3.9/sets/{0}'.format(
        quizletDeckID)
    itemsUrl = 'https://quizlet.com/webapi/3.9/studiable-item-documents?filters%5BstudiableContainerId%5D={0}&filters%5BstudiableContainerType%5D=1&perPage={1}&page=1'.format(
        quizletDeckID, 2000)

    deckResponse = requests.get(deckUrl, verify=False, headers=headers)
    itemsResponse = requests.get(
        itemsUrl, verify=False, headers=headers)

    rawJson = {"studiableDocumentData": json.loads(
        itemsResponse.text)["responses"][0]["models"]}

    items = mapItems(rawJson)
    title = json.loads(deckResponse.text)["responses"][
        0]['models']['set'][0]['title']

    print(json.dumps(items, indent=4, sort_keys=True))


def run():
    try:
        text = None
        results = None
        with open('./examples/diagram.html', 'r') as file:
            text = file.read()

        regex = re.escape('window.Quizlet["setPasswordData"]')

        if re.search(regex, text):
            return

        regex = re.escape('window.Quizlet["setPageData"] = ')
        regex += r'(.+?)'
        regex += re.escape('; QLoad("Quizlet.setPageData");')
        m = re.search(regex, text)

        if not m:
            regex = re.escape('window.Quizlet["assistantModeData"] = ')
            regex += r'(.+?)'
            regex += re.escape('; QLoad("Quizlet.assistantModeData");')
            m = re.search(regex, text)

        if not m:
            regex = re.escape('window.Quizlet["cardsModeData"] = ')
            regex += r'(.+?)'
            regex += re.escape('; QLoad("Quizlet.cardsModeData");')
            m = re.search(regex, text)

        data = m.group(1).strip()
        results = {}
        results['items'] = mapItems(json.loads(data))

        m = re.search(r'<title>(.+?)</title>', text)
        if m:
            title = m.group(1)
            title = re.sub(r' \| Quizlet$', '', title)
            title = re.sub(r'^Flashcards ', '', title)
            title = re.sub(r'\s+', ' ', title)
            title = title.strip()
        results['title'] = title

        print(json.dumps(results, indent=4, sort_keys=True))
    except ValueError as e:
        # print ("Invalid json: {0}".format(e))
        print('error 1')
    except Exception as e:
        print("Invalid json: {0}".format(e))
        # print ("{}\n-----------------\n{}".format(e, text))
    # yep, we got it


run()
