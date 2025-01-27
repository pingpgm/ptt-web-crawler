# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import print_function

import os
import re
import sys
import json
import requests
import argparse
import time
import codecs
from bs4 import BeautifulSoup
from six import u

__version__ = '1.0'

# if python 2, disable verify flag in requests.get()
VERIFY = True
if sys.version_info[0] < 3:
    VERIFY = False
    requests.packages.urllib3.disable_warnings()


class PttWebCrawler(object):
    PTT_URL = 'https://www.ptt.cc'

    """docstring for PttWebCrawler"""

    def __init__(self, cmdline=None, as_lib=False):
        parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description='''
            A crawler for the web version of PTT, the largest online community in Taiwan.
            Input: board name and page indices (or articla ID)
            Output: BOARD_NAME-START_INDEX-END_INDEX.json (or BOARD_NAME-ID.json)
        ''')
        parser.add_argument('-b', metavar='BOARD_NAME', help='Board name', required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('-i', metavar=('START_INDEX', 'END_INDEX'), type=int, nargs=2, help="Start and end index")
        group.add_argument('-a', metavar='ARTICLE_ID', help="Article ID")
        parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__)

        if not as_lib:
            if cmdline:
                args = parser.parse_args(cmdline)
            else:
                args = parser.parse_args()
            board = args.b
            if args.i:
                start = args.i[0]
                if args.i[1] == -1:
                    end = self.getLastPage(board)
                else:
                    end = args.i[1]
                self.parse_articles(start, end, board)
            else:  # args.a
                article_id = args.a
                self.parse_article(article_id, board)

    def parse_articles(self, start, end, board, path='.', timeout=3, skip_links=list, return_file_path=True):
        filename = board + '-' + str(start) + '-' + str(end) + '.json'
        filename = os.path.join(path, filename)
        self.store(filename, u'{"articles": [', 'w')
        articles = []
        for i in range(end - start + 1):
            index = start + i
            print('Processing index:', str(index))
            resp = requests.get(
                url=self.PTT_URL + '/bbs/' + board + '/index' + str(index) + '.html',
                cookies={'over18': '1'}, verify=VERIFY, timeout=timeout
            )
            if resp.status_code != 200:
                print('invalid url:', resp.url)
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            divs = soup.find_all("div", "r-ent")
            for div in divs:
                try:
                    # ex. link would be <a href="/bbs/PublicServan/M.1127742013.A.240.html">Re: [問題] 職等</a>
                    href = div.find('a')['href']
                    link = self.PTT_URL + href
                    if link in skip_links:
                        continue
                    article_id = re.sub('\.html', '', href.split('/')[-1])
                    if return_file_path:
                        if div == divs[-1] and i == end - start:  # last div of last page
                            self.store(filename, self.parse(link, article_id, board), 'a')
                        else:
                            self.store(filename, self.parse(link, article_id, board) + ',\n', 'a')
                    else:
                        articles.append(self.parse(link, article_id, board, return_json_str=return_file_path))
                except:
                    pass
            time.sleep(0.1)
        if return_file_path:
            self.store(filename, u']}', 'a')
        else:
            articles = [article for article in articles if article is not None]
        return filename if return_file_path else articles

    def parse_article(self, article_id, board, path='.'):
        link = self.PTT_URL + '/bbs/' + board + '/' + article_id + '.html'
        filename = board + '-' + article_id + '.json'
        filename = os.path.join(path, filename)
        self.store(filename, self.parse(link, article_id, board), 'w')
        return filename

    @staticmethod
    def decrypt_protected_email(data):
        try:
            r = int(data[:2], 16)
            email = ''.join([chr(int(data[i:i + 2], 16) ^ r) for i in range(2, len(data), 2)])
            return email
        except (ValueError):
            return ''

    @staticmethod
    def parse_meta(meta):
        protected_emails = meta.select(".__cf_email__")

        for protected_email in protected_emails:
            protected_email_data = protected_email["data-cfemail"]
            email_data = PttWebCrawler.decrypt_protected_email(protected_email_data)
            protected_email.replaceWith(email_data)

        return meta.text

    @staticmethod
    def parse(link, article_id, board, timeout=3, return_json_str=True):
        print('Processing article:', article_id)
        resp = requests.get(url=link, cookies={'over18': '1'}, verify=VERIFY, timeout=timeout)
        if resp.status_code != 200:
            print('invalid url:', resp.url)
            return json.dumps({"error": "invalid url"}, sort_keys=True, ensure_ascii=False) if return_json_str else None
        soup = BeautifulSoup(resp.text, 'html.parser')
        main_content = soup.find(id="main-content")
        metas = main_content.select('div.article-metaline')
        author = ''
        title = ''
        date = ''
        if metas:
            author = PttWebCrawler.parse_meta(metas[0].select('span.article-meta-value')[0])
            title = PttWebCrawler.parse_meta(metas[1].select('span.article-meta-value')[0])
            date = PttWebCrawler.parse_meta(metas[2].select('span.article-meta-value')[0])

            # remove meta nodes
            for meta in metas:
                meta.extract()
            for meta in main_content.select('div.article-metaline-right'):
                meta.extract()

        # remove and keep push nodes
        pushes = main_content.find_all('div', class_='push')
        for push in pushes:
            push.extract()

        try:
            ip = main_content.find(text=re.compile(u'※ 發信站:'))
            ip = re.search('[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*', ip).group()
        except:
            ip = "None"

        # 移除 '※ 發信站:' (starts with u'\u203b'), '◆ From:' (starts with u'\u25c6'), 空行及多餘空白
        # 保留英數字, 中文及中文標點, 網址, 部分特殊符號
        filtered = [v for v in main_content.stripped_strings if v[0] not in [u'※', u'◆'] and v[:2] not in [u'--']]
        expr = re.compile(
            u(r'[^\u4e00-\u9fa5\u3002\uff1b\uff0c\uff1a\u201c\u201d\uff08\uff09\u3001\uff1f\u300a\u300b\s\w:/-_.?~%()]'))
        for i in range(len(filtered)):
            filtered[i] = re.sub(expr, '', filtered[i])

        filtered = [_f for _f in filtered if _f]  # remove empty strings
        filtered = [x for x in filtered if article_id not in x]  # remove last line containing the url of the article
        content = ' '.join(filtered)
        content = re.sub(r'(\s)+', ' ', content)
        # print 'content', content

        # push messages
        p, b, n = 0, 0, 0
        messages = []
        for push in pushes:
            if not push.find('span', 'push-tag'):
                continue
            push_tag = push.find('span', 'push-tag').string.strip(' \t\n\r')
            push_userid = push.find('span', 'push-userid').string.strip(' \t\n\r')
            # if find is None: find().strings -> list -> ' '.join; else the current way
            push_content = push.find('span', 'push-content').strings
            push_content = ' '.join(push_content)[1:].strip(' \t\n\r')  # remove ':'
            push_ipdatetime = push.find('span', 'push-ipdatetime').string.strip(' \t\n\r')
            messages.append({'push_tag': push_tag, 'push_userid': push_userid, 'push_content': push_content,
                             'push_ipdatetime': push_ipdatetime})
            if push_tag == u'推':
                p += 1
            elif push_tag == u'噓':
                b += 1
            else:
                n += 1

        # count: 推噓文相抵後的數量; all: 推文總數
        message_count = {'all': p + b + n, 'count': p - b, 'push': p, 'boo': b, "neutral": n}

        # print 'msgs', messages
        # print 'mscounts', message_count

        board, aid = PttWebCrawler.get_aid_from_url(link)

        # json data
        data = {
            'url': link,
            'board': board,
            'aid': aid,
            'article_id': article_id,
            'article_title': title,
            'author': author,
            'date': date,
            'content': content,
            'ip': ip,
            'message_count': message_count,
            'messages': messages
        }
        # print 'original:', d
        return json.dumps(data, sort_keys=True, ensure_ascii=False) if return_json_str else data

    @staticmethod
    def get_aid_from_url(url: str) -> (str, str):
        # from get_aid_from_url in PyPtt

        # 檢查是否符合 PTT BBS 文章網址格式
        pattern = re.compile('https://www.ptt.cc/bbs/[-.\w]+/M.[\d]+.A[.\w]*.html')
        r = pattern.search(url)
        if r is None:
            raise ValueError('url must be www.ptt.cc article url')

        # 演算法參考 https://www.ptt.cc/man/C_Chat/DE98/DFF5/DB61/M.1419434423.A.DF0.html
        # aid 字元表
        aid_table = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'

        board = url[23:]
        board = board[:board.find('/')]

        temp = url[url.rfind('/') + 1:].split('.')
        # print(temp)

        id_0 = int(temp[1])  # dec

        aid_0 = ''
        for _ in range(6):
            index = id_0 % 64
            aid_0 = f'{aid_table[index]}{aid_0}'
            id_0 = int(id_0 / 64)

        if temp[3] != 'html':
            id_1 = int(temp[3], 16)  # hex
            aid_1 = ''
            for _ in range(2):
                index = id_1 % 64
                aid_1 = f'{aid_table[index]}{aid_1}'
                id_1 = int(id_1 / 64)
        else:
            aid_1 = '00'

        aid = f'#{aid_0}{aid_1}({board})'

        return board, aid

    @staticmethod
    def getLastPage(board, timeout=3):
        content = requests.get(
            url='https://www.ptt.cc/bbs/' + board + '/index.html',
            cookies={'over18': '1'}, timeout=timeout
        ).content.decode('utf-8')
        first_page = re.search(r'href="/bbs/' + board + '/index(\d+).html">&lsaquo;', content)
        if first_page is None:
            return 1
        return int(first_page.group(1)) + 1

    @staticmethod
    def store(filename, data, mode):
        with codecs.open(filename, mode, encoding='utf-8') as f:
            f.write(data)

    @staticmethod
    def get(filename, mode='r'):
        with codecs.open(filename, mode, encoding='utf-8') as f:
            return json.load(f)


if __name__ == '__main__':
    c = PttWebCrawler()
