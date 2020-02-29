#!/bin/bash

rm -rf ./build \
&& mkdir build \
&& cp __init__.py config.json meta.json ./build \
&& cd build \
&& zip -r ../quizlet_importer.ankiaddon * \
&& cd ../ \
&& rm -rf ./build