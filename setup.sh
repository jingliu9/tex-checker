#! /bin/bash

set -e

git submodule update --init

# rg (highlight grep)
sudo apt-get -y install ripgrep
sudo apt-get -y install aspell

# Note, conda might also have 'pandoc' installed; if so, uninstall it and use this instead
wget https://github.com/jgm/pandoc/releases/download/2.16.1/pandoc-2.16.1-1-amd64.deb
sudo dpkg -i pandoc*.deb
rm -rf pandoc*.deb

pip install pynput
pip install colorama
pip install gscholar
pip install yapf
cd ./bibtex-dblp || exit
python3 setup.py install

