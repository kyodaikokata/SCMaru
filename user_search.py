"""Offline nickname matching by text, pinyin and pinyin initials."""
from functools import lru_cache
import re
import unicodedata
from pypinyin import lazy_pinyin, pinyin, Style


def compact(value):
    value=unicodedata.normalize('NFKD',unicodedata.normalize('NFKC',str(value))).casefold()
    value=value.replace('u\u0308','v')
    value=''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[\s_\-·.]+','',value)


@lru_cache(maxsize=8192)
def variants(name):
    full=''.join(lazy_pinyin(name,style=Style.NORMAL,strict=False))
    initials=''.join(lazy_pinyin(name,style=Style.FIRST_LETTER,strict=False))
    return compact(name),compact(full),compact(initials)


def matches_user(name, query):
    name=str(name or '')
    needle=compact(query)
    if not needle or any(needle in value for value in variants(name)): return True
    full,initials=alternate_readings(name)
    return contains_reading(full,needle) or contains_reading(initials,needle)


@lru_cache(maxsize=8192)
def alternate_readings(name):
    rows=pinyin(name,style=Style.NORMAL,heteronym=True,strict=False,errors=lambda value:list(value))
    full=tuple(tuple(dict.fromkeys(compact(value) for value in row)) for row in rows)
    initials=tuple(tuple(dict.fromkeys(value[:1] for value in row)) for row in full)
    return full,initials


def contains_reading(rows,needle):
    """KMP states match alternate readings without expanding their combinations."""
    prefix=[0]*len(needle)
    for i in range(1,len(needle)):
        k=prefix[i-1]
        while k and needle[i]!=needle[k]: k=prefix[k-1]
        if needle[i]==needle[k]: k+=1
        prefix[i]=k
    states={0}
    for choices in rows:
        following=set()
        for state in states:
            for token in choices:
                k=state
                for char in token:
                    while k and needle[k]!=char: k=prefix[k-1]
                    if needle[k]==char: k+=1
                    if k==len(needle): return True
                following.add(k)
        states=following or {0}
    return False
