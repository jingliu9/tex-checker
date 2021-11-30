#! /usr/bin/env python3

import logging
import os
import argparse
import sys
import subprocess
import re
import random
import json
from pathlib import Path
import gscholar
import time
import bibtex_dblp.dblp_api as dblp_api

import colorama

colorama.init(autoreset=True)

YELLOW = "\x1b[1;33;40m"


class TexChecker(object):

    def __init__(self, root_file, skip_fname=None, inter=False, no_rec=False):
        self.root_file = os.path.abspath(root_file)
        self.root_dir = (Path(self.root_file)).parent
        self.inter = inter
        logging.debug(self.root_dir)
        self.tex_source_files = []
        self.skip_list = []
        # load the skip words
        if skip_fname is not None:
            self._init_skip_list(skip_fname)
        # recursively check or not
        if no_rec:
            self.tex_source_files.append(root_file)
        else:
            self._resolve_source_files(self.root_file)

    def check(self):
        idx = 0
        for fname in self.tex_source_files:
            self._check_single_file(fname)
            if self.inter:
                idx += 1
                if len(self.tex_source_files) > idx:
                    print(
                        f"\n{YELLOW}type ENTER to go on processing {self.tex_source_files[idx]} | q (quit): ",
                        end='')
                    yes_or_no = input()
                    if not yes_or_no:
                        continue
                    else:
                        sys.exit(0)

    def _init_skip_list(self, skip_fname):
        with open(skip_fname) as f:
            for line in f:
                line = line.strip()
                # line start with '##' is treated as comment
                if len(line) > 1 and line[0:2] != '##':
                    self.skip_list.append(line)

    def _resolve_source_files(self, cur_fname):
        with open(cur_fname) as f:
            self.tex_source_files.append(cur_fname)
            for line in f:
                m = re.match(r'\\(include|input)\{(.*?)\}', line)
                if m:
                    logging.debug(m.group(2))
                    next_fname = '{}/{}.tex'.format(self.root_dir, m.group(2))
                    self._resolve_source_files(next_fname)

    def _check_single_file(self, fname):
        tmp_words = '.words'
        cmd = 'cat {} | aspell --ignore=2 list -t | sort | uniq'.format(fname)
        logging.info('>>>>>>> {}'.format(fname))
        with open(tmp_words, 'w') as f:
            subprocess.run(cmd, shell=True, stdout=f)
        with open(tmp_words) as f:
            for line in f:
                line = line.strip()
                if len(line) > 2 and line not in self.skip_list:
                    subprocess.run('rg {} {}'.format(line, fname), shell=True)
        os.remove(tmp_words)


class BibChecker(object):

    def __init__(self,
                 bibaux,
                 bibitems=None,
                 bibjson=None,
                 inter=False,
                 reuse=False):
        self.USE_DBLP = True
        tmp_path_items = [s for s in re.split('\.|/', bibitems) if s]
        self.FILE_DIR = 'CHECK-{}'.format(('-'.join(tmp_path_items)))
        if not os.path.exists(self.FILE_DIR):
            os.mkdir(self.FILE_DIR)
        self.inter = inter
        self.reuse = reuse
        self.bibaux = bibaux  #.aux
        self.bibitems = bibitems  #.bib
        self.cited_bibs = {}
        self.cited_json_items = {}
        if bibjson is None:
            # generate json for the given bib for further processing
            self.bib_json_name = '{}/{}.json'.format(self.FILE_DIR,
                                                     bibitems.split('/')[-1])
            assert (bibitems is not None)
            self._match_bibitems()
        else:
            # use supplied json
            assert (os.path.exists(bibjson))
            self.bib_json_name = bibjson
        self._load_citation()
        self._load_cited_bibentries()
        self._download_citation()

    @staticmethod
    def check_dependencies():
        BibChecker._check_pandoc_version()

    @staticmethod
    def _check_pandoc_version():
        cmd = 'pandoc --version | head -n 1 | awk \'{print $2}\''
        p = subprocess.run(cmd, capture_output=True, shell=True)
        version_str = p.stdout.decode('utf-8').strip()
        vers = version_str.split('.')
        vers_list = list(map(int, vers))
        if vers_list[0] < 2 or vers_list[1] < 16:
            raise RuntimeError("requires pandoc version >= 2.16")

    def _load_citation(self):
        with open(self.bibaux) as f:
            for line in f:
                line = line.strip()
                m = re.match(r'\\(bibcite)\{(.*?)\}', line)
                if m:
                    logging.debug(m.group(2))
                    self.cited_bibs[m.group(2)] = line

    def _match_bibitems(self):
        # gen bib items to json
        cmd = 'pandoc {}  -s -f biblatex -t csljson -o {}'.format(
            self.bibitems, self.bib_json_name)
        subprocess.run(cmd, shell=True)

    def _load_cited_bibentries(self):
        with open(self.bib_json_name) as f:
            data = json.load(f)
            for item in data:
                if item["id"] in self.cited_bibs:
                    logging.debug(item["id"])
                    self.cited_json_items[item["id"]] = item
        # all the cited bibitems are found
        assert (len(self.cited_json_items) == len(self.cited_bibs))

    def _download_web_bib(self, paper_title, save_name, target_year=None):
        pub_bibtex = None
        if os.path.exists(save_name) and self.reuse:
            logging.info('{} exists, so skip downloading'.format(save_name))
            return True
        if self.USE_DBLP:
            paper_title = paper_title.replace(u'’', u"'")
            # use dblp
            search_result = dblp_api.search_publication(paper_title,
                                                        max_search_results=5)
            if search_result is not None and search_result.total_matches > 0:
                # try to match the year
                select_idx = 0
                year_matched = False
                if target_year is not None:
                    for idx, pub in enumerate(search_result.results):
                        if pub.publication.year == target_year:
                            year_matched = True
                            select_idx = idx
                            break
                # the first that is a conference to select
                if not year_matched:
                    for idx, pub in enumerate(search_result.results):
                        if 'conference' in pub.publication.type.lower():
                            select_idx = idx
                            break
                publication = search_result.results[select_idx].publication
                pub_bibtex = dblp_api.get_bibtex(
                    publication.key, bib_format=dblp_api.BibFormat.condensed)
        else:
            # use google scholar
            gs_bib_list = gscholar.query(paper_title)
            if len(gs_bib_list) > 0:
                pub_bibtex = gs_bib_list[0]
        if pub_bibtex is not None:
            with open(save_name, 'w') as f:
                f.write(pub_bibtex)
        return pub_bibtex is not None

    def _download_citation(self):
        for idx, item_name in enumerate(self.cited_json_items.keys()):
            cur_item = self.cited_json_items[item_name]
            if 'title' not in cur_item:
                continue
            web_bib_name = '{}/web-{}.bib'.format(self.FILE_DIR, item_name)
            logging.info('{} - {}'.format(item_name, cur_item['title']))
            cur_item_year = None
            if "issued" in cur_item and "date-parts" in cur_item["issued"]:
                cur_item_year = cur_item["issued"]["date-parts"][0][0]
            download_ok = self._download_web_bib(cur_item['title'],
                                                 web_bib_name, cur_item_year)
            if download_ok:
                web_bib_json_name = web_bib_name + '.json'
                cmd = 'pandoc {} -s -f biblatex -t csljson -o {}'.format(
                    web_bib_name, web_bib_json_name)
                subprocess.run(cmd, shell=True)
                with open(web_bib_json_name) as f:
                    cur_web_bib_json = (json.load(f))[0]
                    if "author" in cur_web_bib_json and "author" in cur_item:
                        cur_web_author_list = cur_web_bib_json["author"]
                        cur_item_author_list = cur_item["author"]
                        cur_not_match = False
                        if (len(cur_web_author_list) !=
                                len(cur_item_author_list)):
                            logging.warning("Author list length not match")
                            cur_not_match = True
                        for a, b in zip(cur_web_author_list,
                                        cur_item_author_list):
                            if "literal" in a or "literal" in b:
                                cur_not_match = True
                                break
                            if a["family"] != b["family"] or a["given"] != b[
                                    "given"]:
                                cur_not_match = True
                                logging.warning("\nW:{} \nL:{}".format(a, b))
                                if a["given"].replace('.',
                                                      '') == b["given"].replace(
                                                          '.', ''):
                                    cur_not_match = False
                    if cur_web_bib_json["issued"]["date-parts"] != cur_item[
                            "issued"]["date-parts"]:
                        logging.warning("Year not match")
                        cur_not_match = True
                    if cur_not_match:
                        print(cur_web_bib_json)
                        print(cur_item)
                        if self.inter:
                            print(f"\n{YELLOW}type ENTER to go on | q (quit): ",
                                  end='')
                            yes_or_no = input()
                            if yes_or_no:
                                sys.exit(0)
            else:
                logging.warning(
                    'Cannot download for title:{}'.format(item_name))
            # avoid burst query
            time.sleep(random.randrange(20, 30))


def main(args, loglevel):
    logging.basicConfig(format="%(levelname)s: %(message)s", level=loglevel)
    if args.tex:
        cur_checker = TexChecker(args.root,
                                 skip_fname=args.words,
                                 inter=args.interactive,
                                 no_rec=args.no_rec)
        cur_checker.check()
    elif args.markdown:
        raise RuntimeError('Markdown not supported yet')
    elif args.bibaux:
        assert (args.bib is not None or args.bibjson is not None)
        BibChecker.check_dependencies()
        cur_checker = BibChecker(args.root,
                                 bibitems=args.bib,
                                 bibjson=args.bibjson,
                                 inter=args.interactive,
                                 reuse=args.reuse)
    else:
        raise RuntimeError('type not supported')


def parse_cmd_args():
    parser = argparse.ArgumentParser(description="Spell Check for Latex")
    # file type
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--tex', action='store_true', help='latex/tex project')
    group.add_argument('--markdown',
                       action='store_true',
                       help='markdown project')
    group.add_argument(
        '--bibaux',
        action='store_true',
        help='cross checking bibtex for references (generated aux)')
    # required
    parser.add_argument('--root',
                        type=str,
                        help='root file path',
                        required=True)

    # optional
    parser.add_argument('--words', help='a file with each line a word to skip')
    parser.add_argument('--interactive',
                        help='need user input to process next file',
                        action='store_true')
    parser.add_argument('--no_rec',
                        help='Not recursively check included files',
                        action='store_true')
    parser.add_argument('--bib', help='bib file contains bibitem.', type=str)
    parser.add_argument(
        '--bibjson',
        help=
        'json file contains the bibitems (csljson), if specified will not use --bib',
        type=str)
    parser.add_argument('--reuse',
                        help='try to reuse downloaded bib items',
                        action='store_true')
    return (parser.parse_args())


if __name__ == '__main__':
    loglevel = logging.INFO
    args = parse_cmd_args()
    main(args, loglevel)
