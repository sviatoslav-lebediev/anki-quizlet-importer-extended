# Quizlet importer Extended

Upgraded version of the quizlet importer which imports audio files.
Instead of creating Front and Back items this version creates these fields

    * FrontText
    * FrontAudio
    * BackText
    * BackAudio
    * Image
    * Add Reverse

Note type name is `Basic Quizlet Extended`;

Supports start and stop phrases. It allows you to download a part of the quizlet collection.

![Preview](https://github.com/sviatoslav-lebediev/anki-quizlet-importer-extended/blob/master/preview.jpg)

### This addon creates two types of cards: Normal and Reverse

**Normal Template has**:

* Front

    ```html
    {{FrontText}}
    <br><br>
    {{FrontAudio}}
    ```

* Back
    ```html
    {{FrontText}}
    <hr id=answer>
    {{BackText}}
    <br><br>
    {{Image}}
    <br><br>
    {{BackAudio}}
    ```

**Reverse Template is**:

* Front
    ```html
    {{#Add Reverse}}
    {{BackText}}
    <br><br>
    {{BackAudio}}
    {{/Add Reverse}}
    ```

* Back
    ```html
    {{BackText}}
    <hr id=answer>
    {{FrontText}}
    <br><br>
    {{FrontAudio}}
    {{Image}}
    ```

### Fields formats

* FrontAudio - `[sound:"quizlet-CARD_ID-front.mp3"]`
* BackAudio - `[sound:"quizlet-CARD_ID-back.mp3"]`
* Image - `<img src="file_name">`
