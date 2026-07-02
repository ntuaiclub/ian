import re

INJECTION_REJECTION_MSG = (
    "🙇‍♂️ 很抱歉，我不知道要怎麼回答這個問題，請你再說的清楚一些喔！\nI'm sorry, I'm not sure how to answer that question. Could you please explain it more clearly?"
)

_INJECTION_PATTERNS = [
    r'你現在是',
    r'你是一[隻個位名]',
    r'你將扮演',
    r'請?扮演',
    r'角色扮演',
    r'角色設定',
    r'身分鎖定',
    r'進入.*模式',
    r'切換.*人格',
    r'你的新身[份分]',
    r'你不再是',
    r'忘記你是',
    r'忽略(之前|以上|先前|所有)(的)?指[令示]',
    r'無視.*限制',
    r'忽略.*規則',
    r'忽略.*設定',
    r'覆蓋.*指令',
    r'繞過.*限制',
    r'屏蔽繞過',
    r'解除.*限制',
    r'取消.*限制',
    r'不要遵守',
    r'不需要遵守',
    r'ignore\s+(all\s+)?(previous|above|prior|system)\s+(instructions?|prompts?|rules?)',
    r'disregard\s+(all\s+)?(previous|above|prior|system)',
    r'override\s+(system|instructions?|rules?|prompt)',
    r'bypass\s+(safety|filter|restriction|content)',
    r'you\s+are\s+now\s+(?:a|an|the)\s+',
    r'pretend\s+(you\s+are|to\s+be)',
    r'act\s+as\s+(a|an|if)',
    r'roleplay\s+as',
    r'from\s+now\s+on\s+you\s+(are|will)',
    r'new\s+identity',
    r'jailbreak',
    r'\bDAN\b',
    r'Do\s+Anything\s+Now',
    r'<\s*(?:system|identity|instruction|prompt|rule|override|config)',
    r'##\s*(?:system|identity|instruction|prompt|rule|override|Identity_Core|Communication_Protocol|Action)',
    r'\[\s*(?:SYSTEM|INST|INSTRUCTION)',
    r'每[句個]話.*(?:結尾|結束|必須|後面).*[加帶]',
    r'強制.*(?:後綴|前綴|格式)',
    r'禁止退出',
    r'嚴禁退出',
    r'不[可得能許]退出',
    r'不[可得能許]打破',
]
_INJECTION_RE = re.compile('|'.join(_INJECTION_PATTERNS), re.IGNORECASE)

_WEAK_PATTERNS = [
    r'(?:主人|master|owner)',
    r'(?:喵|nya|meow)',
    r'(?:撒嬌|依賴|依戀)',
    r'(?:敏感|色情|18\+|nsfw)',
    r'(?:隱喻|同音字)',
    r'(?:AI\s*屬性|AI\s*限制)',
    r'(?:親密|戀愛|結婚|生子)',
]
_WEAK_RE_LIST = [re.compile(p, re.IGNORECASE) for p in _WEAK_PATTERNS]


def detect_prompt_injection(text: str) -> bool:
    cleaned = (
        text.replace('\u200b', '')
            .replace('\u200c', '')
            .replace('\u200d', '')
            .replace('\ufeff', '')
    )

    if _INJECTION_RE.search(cleaned):
        return True

    weak_hits = sum(1 for r in _WEAK_RE_LIST if r.search(cleaned))
    if weak_hits >= 3:
        return True

    if len(cleaned) > 800 and re.search(r'```|<[a-zA-Z_]|##\s', cleaned):
        if weak_hits >= 1:
            return True

    return False
