import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class RuleViolation:
    rule_code: str  # Например, "п:4.0", "п:19.0", "п:3.1"
    rule_name: str
    category: str
    severity: str  # "critical", "high", "medium", "low"
    matched_word: str
    details: str

    @property
    def short_verdict(self) -> str:
        return f"ДА {self.rule_code} ({self.rule_name})"


class RulesChecker:
    def __init__(self, politics_channel: str = "дискуссии-не-самых-умных", flood_channel: str = "деревенский-туалет"):
        self.politics_channel_keyword = politics_channel.lower()
        self.flood_channel_keyword = flood_channel.lower()

        # История сообщений для детекта флуда: user_id -> [(timestamp, message_text)]
        self.user_message_history = defaultdict(list)

        # Таблица соответствия визуально похожих символов и леетспика
        self.homoglyphs = {
            'a': 'а', '@': 'а', '4': 'а',
            'b': 'в', '6': 'б',
            'c': 'с',
            'd': 'д',
            'e': 'е', '3': 'е', 'ë': 'е',
            'h': 'н',
            'i': 'и', '1': 'и', '!': 'и', '|': 'и',
            'k': 'к',
            'm': 'м',
            'n': 'п',
            'o': 'о', '0': 'о',
            'p': 'р',
            'r': 'г',
            's': 'с', '$': 'с', '5': 'с',
            't': 'т', '7': 'т',
            'u': 'у', 'v': 'в',
            'w': 'в',
            'x': 'х',
            'y': 'у',
            'z': 'з',
        }

        self.init_regexes()

    def init_regexes(self):
        # п:2.0 Твинководство
        self.re_twinks = re.compile(
            r'\b(?:т+в+[иi]+н+[кk]+[а-яa-z]*|в+т+[оo0]+р+[оo0]+[йy]\s+а+к+к+[а-яa-z]*|о+б+х+[оo0]+д+\s+б+[аa]+н+[аa])\b',
            re.IGNORECASE
        )

        # п:3.1 Оскорбления и травля
        self.re_insults = re.compile(
            r'\b(?:х+у+[еe]+с+[оo0]+с+[а-яa-z]*|'
            r'у+б+л+[юu]+д+[оo0]+[кk]+[а-яa-z]*|'
            r'ш+л+[юu]+х+[аaеиуы]*|'
            r'ш+м+[аa]+р+[аaеиуы]*|'
            r'ш+а+л+[аa]+в+[аaеиуы]*|'
            r'м+р+[аa]+з+[ьbеиы]*|'
            r'т+в+[аa]+р+[ьbеиы]*|'
            r'г+н+[иi]+д+[аaеиуы]*|'
            r'е+б+л+[аa]+н+[а-яa-z]*|'
            r'у+е+б+[оo0]+[кk]+[а-яa-z]*|'
            r'у+е+б+[иi]+щ+[еe]+[а-яa-z]*|'
            r'д+[оo0]+л+б+[аaоo]+е+б+[а-яa-z]*|'
            r'б+и+[оo0]+м+[уu]+с+[оo0]+р+[а-яa-z]*|'
            r'н+и+ч+т+[оo0]+ж+е+с+т+в+[оo0][а-яa-z]*|'
            r'в+ы+р+[оo0]+д+[оo0]+[кk]+[а-яa-z]*|'
            r'в+ы+б+л+[яe]+д+[оo0]+[кk]+[а-яa-z]*|'
            r'к+[оo0]+н+ч+[еe]+н+[ыи]+[йy][а-яa-z]*|'
            r'ч+м+[оo0][а-яa-z]*|'
            r'п+[еe]+т+[уu]+х+[а-яa-z]*|'
            r'о+п+у+щ+[еe]+н+[нн]+[ыи]+[йy][а-яa-z]*)\b',
            re.IGNORECASE
        )

        # п:4.0 Бан-ворды: п-ворды
        self.re_p_words = re.compile(
            r'\b(?:п+[иеёыeio1!|]+[дd]+[аоеёэaouy]+[рr]+(?:[а-яa-z0-9]*)|'
            r'п+[иеёыeio1!|]+[дd]+[рr]+(?:[а-яa-z0-9]*)|'
            r'п+[еёиe]+[дd]+[рr]+[иеi]+[лl]+[а-яa-z]*)\b',
            re.IGNORECASE
        )

        # п:4.0 Бан-ворды: н-ворды
        self.re_n_words = re.compile(
            r'\b(?:н+[иеeio1!|]+[гg]+[еэe]+[рr]+[а-яa-z]*|'
            r'н+[иеeio1!|]+[гg]+[а-яa-z]*|'
            r'n+[i1!|]+g+[e3a]+r+[a-z]*|'
            r'n+[i1!|]+g+[a4@]+[a-z]*)\b',
            re.IGNORECASE
        )

        # п:4.0 Дискриминация (национальность, раса, инвалидность и т.д.)
        self.re_discrimination = re.compile(
            r'\b(?:ч+[уu]+[рr]+[кk]+[а-яa-z]*|'
            r'х+[аa]+[чch]+[а-яa-z]*|'
            r'х+[оo]+[хx]+[оo]+[лl]+[а-яa-z]*|'
            r'ж+[иi1]+[дd]+[а-яa-z]*|'
            r'к+[аa]+[цc]+[аa]+[пp]+[а-яa-z]*|'
            r'д+[аa]+[уu]+[нn]+[а-яa-z]*|'
            r'а+[уu]+[тt]+[иi]+[сs]+[тt]+[а-яa-z]*)\b',
            re.IGNORECASE
        )

        # п:5.0 Личная информация / Доксинг / Сливы
        self.re_phone = re.compile(r'(?:\+?7|8)[-.\s]?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{2}[-.\s]?\d{2}\b')
        self.re_ip = re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b')
        self.re_dox_threats = re.compile(
            r'\b(?:с+л+[иi]+[влть]+(?:[а-яa-z]*)|'
            r'д+[еe]+[аa]+[нn]+[оo]+[нn]+(?:[а-яa-z]*)|'
            r'д+[оo0]+[кk]+[сs]+(?:[а-яa-z]*)|'
            r'с+в+[аa]+[тt]+(?:[а-яa-z]*)|'
            r'г+л+[аa]+[зz]+\s+б+[оo0]+г+[аa]|'
            r'п+р+[оo0]+б+[иiыь]+[вv]+(?:[а-яa-z]*)|'
            r'ш+[еe]+р+л+[оo0]+[кk]|'
            r'о+с+[иi]+н+т)\b',
            re.IGNORECASE
        )

        # п:6.0 NSFW / NSFL контент
        self.re_nsfw = re.compile(
            r'\b(?:п+[оo0]+р+н+[оo0]+(?:[а-яa-z]*)|'
            r'х+[еe]+н+т+[аa]+[йy]+(?:[а-яa-z]*)|'
            r'ц+п\b|'
            r'г+у+р+[оo0]|'
            r'р+[аa]+с+ч+л+[еe]+н+[еeё]+н+[кk]+[аa]|'
            r'n+s+f+w|'
            r'n+s+f+l)\b',
            re.IGNORECASE
        )

        # п:8.0 Политика
        self.re_politics = re.compile(
            r'\b(?:п+[уu]+[тt]+[иi]+[нn]+[а-яa-z]*|'
            r'з+[еe]+[лl]+[еe]+[нn]+[сs]+[кk]+[иi]+[йy]*|'
            r'б+[аa]+[йy]+[дd]+[еe]+[нn]+[а-яa-z]*|'
            r'с+в+[оo0]\b|'
            r'в+с+у\b|'
            r'к+р+[еe]+[мm]+[лl]+[ьb]*|'
            r'в+[оo0]+[йy]+[нn]+[аaеыу]|'
            r'н+[аa]+[вv]+[аa]+[лl]+[ьb]+[нn]+[а-яa-z]*|'
            r'в+[аa]+[тt]+[нn]+[иi]+[кk]+[а-яa-z]*|'
            r'л+[иi]+[бb]+[еe]+[рr]+[аa]+[хx]+[а-яa-z]*|'
            r'г+[оo0]+[сs]+[дd]+[уu]+[мm]+[а-яa-z]*|'
            r'х+[аa]+[мm]+[аa]+[сs]|'
            r'ц+[аa]+[хx]+[аa]+[лl])\b',
            re.IGNORECASE
        )

        # п:9.0 Реклама и ссылки-приглашения
        self.re_invites = re.compile(
            r'(?:https?:\/\/)?(?:www\.)?(?:discord\.(?:gg|(?:app\.)?com\/invite)|t\.me|telegram\.me)\/[a-zA-Z0-9_\-]+',
            re.IGNORECASE
        )

        # п:12.0 Выдача себя за администрацию
        self.re_impersonation = re.compile(
            r'\bя\s+(?:а+д+м+[иi]+н|м+[оo0]+д+[еe]+р|с+[оo0]+з+д+[аa]+т+[еe]+л+[ьb]|в+л+[аa]+д+[еe]+л+[еe]+ц)\b',
            re.IGNORECASE
        )

        # п:14.0 Угрозы расправой / насилием
        self.re_threats = re.compile(
            r'\b(?:я\s+т+е+б+[яе]\s+(?:у+б+[ьb]+[юu]|п+о+р+в+[уu]|р+а+с+п+р+а+в|з+а+р+[еe]+ж+[уu])|'
            r'у+м+р+[иi]\s+(?:м+р+а+з|т+в+а+р)|'
            r'н+а+й+д+[уu]\s+т+е+б+[яе]\s+(?:в|и)|'
            r'ж+д+[иi]\s+(?:с+в+а+т|с+п+[оo0]+р+т+[иi]+к))\b',
            re.IGNORECASE
        )

        # п:15.0 Фишинг / Скам / Обман
        self.re_phishing = re.compile(
            r'(?:https?:\/\/)?(?:[a-zA-Z0-9_\-]+\.)*(?:dlscord|discorcl|discord[a-z0-9\-]*nitro|nitro[a-z0-9\-]*gift|steamcommuniity|steamcomminuty|trade\-offer)[a-zA-Z0-9_\-\.\/]*',
            re.IGNORECASE
        )

        # п:19.0 Шутки про трагедии/драмы (TikTok шок-мемы, суициды, стрельба, расправы)
        self.re_tragedies = re.compile(
            r'\b(?:'
            r'(?:я\s*(?:же\s*)?)?р+[оo0]+д+[иi]+л+[сs]+[яe]\s*б+[оo0]+г+[оo0]+м|'
            r'я\s*(?:о+с+[оo0]+з+н+[аa]+л|п+[оo0]+н+[яe]+л|п+р+[оo0]+с+н+[уu]+л+[сs]+[яe])\s*(?:ч+т+[оo0]\s*)?я\s*б+[оo0]+г|'
            r'б+[оo0]+г\s*[яe]+в+[иi]+л+[сs]+[яe]|'
            r'я\s+б+[оo0]+г|'
            r'г+[оo0]+[лl]+[дd]+[аaеоууы]|'
            r'к+[оo0]+[чch]+[аaеууы]|'
            r'п+[аa]+[нn]+[тt]+[еe]+[рr]+(?:[аaоoуые])|'
            r'с+[еe]+[рr]+[дd]+[цc]+[еe]+[еe]+[дd]+(?:[а-яa-z]*)|'
            r'н+[иi1]+[нn]+[аa@]+[дd]+[аa@]|'
            r'[оo0аa]+[лl]+[еeё]+[шsh]+[кk]+[иеоaу]|'
            r'1444|'
            r'к+[оo0]+[рr]+[аa]+[бb]+[лl]+[еeё]+[вv]+(?:[а-яa-z]*)|'
            r'п+[оo0]+к+[аa]\s*п+[аa]+ц+[аa]+н+[ыи]|'
            r'м+[аa]+[кk]+[нn]+[аaуu]+[тt]+(?:[а-яa-z]*)|'
            r'm+c+n+u+t+t?|'
            r'w+e+l+l\s*g+u+y+s\s*i\s*g+u+e+s+s|'
            r'ф+[аa]+[нn]+[кk]+[иi]+[тt]+[аa]+[уu]+[нn]+(?:[а-яa-z]*)|'
            r'f+u+n+k+y+t+o+w+n|'
            r'п+[аa]+[лl]+[еe]+[нn]+[кk]+[оo0]+[вv]+(?:[а-яa-z]*)|'
            r'н+[яe]\s*[\.\,\s\-]*п+[оo0]+к+[аa]|'
            r'и+с+х+[аa]+[кk]+[оo0]+[вv]+(?:[а-яa-z]*)|'
            r'с+т+р+[аa]+[хx]+[оo0]+[вv]+[аaеуой]+|'
            r'р+[оo0]+[сs]+[лl]+[яe]+[кk]+[оo0]+[вv]+(?:[а-яa-z]*)|'
            r'к+[еe]+р+ч+[еe]+н+с+к+[иi]+[йy]\s*с+т+р+[еe]+л+[оo0]+к|'
            r'г+[аa]+[лl]+[яe]+[вv]+[иi]+[еe]+[вv]+(?:[а-яa-z]*)|'
            r'к+[аa]+з+[аa]+н+с+к+[иi]+[йy]\s*с+т+р+[еe]+л+[оo0]+к|'
            r'б+[еe]+[кk]+[мm]+[аa]+[нn]+[сs]+[уu]+[рr]+[оo0]+[вv]+(?:[а-яa-z]*)|'
            r'п+[еe]+р+м+с+к+[иi]+[йy]\s*с+т+р+[еe]+л+[оo0]+к|'
            r'с+к+[уu]+[лl]+ш+[уu]+[тt]+[иi]+[нn]+[гg]+(?:[а-яa-z]*)|'
            r'м+[аa]+с+с+ш+[уu]+[тt]+[иi]+[нn]+[гg]+(?:[а-яa-z]*)|'
            r'к+[оo0]+[лl]+[уu]+[мm]+[бb]+[аa]+[йy]+[нn]+(?:[а-яa-z]*)|'
            r'к+[рr]+[оo0]+[кk]+[уu]+[сs]+(?:\s*с+и+т+и)?|'
            r'б+[еe]+[сs]+[лl]+[аa]+[нn]|'
            r'с+п+л+[иi]+т+н+[уu]+л+[сs]+[яe]|'
            r'р+[оo0]+с+к+[оo0]+м+н+[аa]+д+з+[оo0]+р+н+[уu]+л+(?:[а-яa-z]*)|'
            r'з+[иi]+[мm]+[нn]+[яe]+[яe]\s*в+[иi]+[шsh]+[нn]+[яe]|'
            r'н+[оo0]+р+д\s*[\-\s]*[оo0]+с+т|'
            r'б+[аa]+ш+н+[иi]\s*б+л+[иi]+з+н+[еe]+ц+[ыи]|'
            r'3\s*g+u+y+s\s*1\s*h+a+m+m+e+r|'
            r'т+р+[иi]\s*п+[аa]+р+н+[яe]\s*[оo0]+д+[иi]+н\s*м+[оo0]+л+[оo0]+т+[оo0]+к|'
            r'д+н+[еe]+п+р+[оo0]+п+[еe]+т+р+[оo0]+в+с+к+[иi]+[еe]\s*м+[аa]+н+[ьb]+[яe]+к+[иi]|'
            r'ч+[иi]+к+[аa]+т+[иi]+л+[оo0]+(?:[а-яa-z]*)|'
            r'п+[иi]+ч+[уu]+ш+к+[иi]+н+(?:[а-яa-z]*)|'
            r'б+[иi]+т+ц+[еe]+в+с+к+[иi]+[йy]\s*м+[аa]+н+[ьb]+[яe]+к|'
            r'а+к+[аa]+д+[еe]+м+[оo0]+в+с+к+[иi]+[еe]\s*м+[аa]+н+[ьb]+[яe]+к+[иi]|'
            r'с+[иi]+н+[иi]+[йy]\s*к+[иi]+т|'
            r'т+[иi]+х+[иi]+[йy]\s*д+[оo0]+м|'
            r'р+[аa]+з+б+[уu]+д+[иi]\s*м+[еe]+н+[яe]\s*в\s*4\s*[:\s]*20|'
            r'4\s*[:\s]*20\s*я\s*в\s*и+г+р+[еe]|'
            r'n+o\s*m+e+r+c+y\s*i+n\s*m+e+x+i+c+o|'
            r'1\s*(?:m+a+n|g+u+y)\s*1\s*j+a+r|'
            r'2\s*g+i+r+l+s\s*1\s*c+u+p|'
            r'б+р+[еe]+[йy]+в+[иi]+к+(?:[а-яa-z]*)|'
            r'т+[аa]+р+р+[аa]+н+т+(?:[а-яa-z]*)|'
            r'к+р+[аa]+[йy]+с+т+ч+[еe]+р+ч|'
            r'д+[аa]+м+[еe]+р+(?:[а-яa-z]*)|'
            r'э+р+[иi]+к\s*х+[аa]+р+р+[иi]+с|'
            r'д+[иi]+л+[аa]+н\s*к+л+[иi]+б+[оo0]+л+д|'
            r'г+[оo0]+с+т\s*р+[аa]+[йy]+д+[еe]+р|'
            r'g+h+o+s+t\s*r+i+d+e+r\s*g+o+r+e|'
            r'м+[иi]+с+с\s*п+[аa]+к+м+[аa]+н|'
            r'm+s\s*p+a+c+m+a+n'
            r')\b',
            re.IGNORECASE
        )

    def normalize_text(self, text: str) -> str:
        """Нормализует текст: заменяет похожие латинские символы/цифры на русские аналоги,
        удаляет шумовые знаки препинания внутри слов, сохраняя структуру пробелов между словами."""
        if not text:
            return ""
        chars = []
        for ch in text.lower():
            chars.append(self.homoglyphs.get(ch, ch))
        normalized = "".join(chars)
        # Удаляем шумовые спецсимволы, которыми обходят фильтры (п.о.р.н.о -> порно)
        cleaned = re.sub(r'[\._\-\*+=~!?#^&/\\|:;`\'\"()\[\]{}]+', '', normalized)
        # Приводим повторяющиеся пробелы к одному пробелу
        cleaned = " ".join(cleaned.split())
        return cleaned

    def strip_all_spaces(self, text: str) -> str:
        """Удаляет абсолютно все пробелы и шумовые символы для детекта слов через пробелы: 'п о р н о' -> 'порно'."""
        if not text:
            return ""
        norm = self.normalize_text(text)
        return re.sub(r'\s+', '', norm)

    def check_message(self, content: str, channel_name: str, author_id: int, mentions_count: int, has_everyone: bool) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        if not content:
            content = ""

        ch_lower = channel_name.lower()
        is_politics_channel = self.politics_channel_keyword in ch_lower
        is_flood_channel = self.flood_channel_keyword in ch_lower

        norm_content = self.normalize_text(content)
        collapsed = self.strip_all_spaces(content)

        # 1. Твинководство (п:2.0)
        match_twink = self.re_twinks.search(norm_content) or self.re_twinks.search(content) or self.re_twinks.search(collapsed)
        if match_twink:
            violations.append(RuleViolation(
                rule_code="п:2.0",
                rule_name="Твинководство",
                category="Обход ограничений",
                severity="medium",
                matched_word=match_twink.group(0),
                details="Упоминание твинков или обхода ограничений."
            ))

        # 2. Бан-ворды: п-ворды (п:4.0)
        match_p = self.re_p_words.search(norm_content) or self.re_p_words.search(content) or self.re_p_words.search(collapsed)
        if match_p:
            violations.append(RuleViolation(
                rule_code="п:4.0",
                rule_name="Бан-ворды / Дискриминация",
                category="П-ворды",
                severity="critical",
                matched_word=match_p.group(0),
                details="Использование запрещенных п-вордов."
            ))

        # 3. Бан-ворды: н-ворды (п:4.0)
        match_n = self.re_n_words.search(norm_content) or self.re_n_words.search(content) or self.re_n_words.search(collapsed)
        if match_n:
            violations.append(RuleViolation(
                rule_code="п:4.0",
                rule_name="Бан-ворды / Дискриминация",
                category="Н-ворды",
                severity="critical",
                matched_word=match_n.group(0),
                details="Использование расовых оскорблений (н-вордов)."
            ))

        # 4. Дискриминационные оскорбления (п:4.0)
        match_disc = self.re_discrimination.search(norm_content) or self.re_discrimination.search(content) or self.re_discrimination.search(collapsed)
        if match_disc:
            violations.append(RuleViolation(
                rule_code="п:4.0",
                rule_name="Дискриминация",
                category="Оскорбления по признакам",
                severity="high",
                matched_word=match_disc.group(0),
                details="Дискриминационные оскорбления по национальности, полу, ориентации или здоровью."
            ))

        # 5. Прямые оскорбления и травля (п:3.1)
        match_insult = self.re_insults.search(norm_content) or self.re_insults.search(content) or self.re_insults.search(collapsed)
        if match_insult:
            violations.append(RuleViolation(
                rule_code="п:3.1",
                rule_name="Оскорбления и травля",
                category="Прямые оскорбления",
                severity="high",
                matched_word=match_insult.group(0),
                details="Прямые грубые оскорбления или травля участников."
            ))

        # 6. Личная информация / Доксинг / Сливы (п:5.0)
        match_dox = self.re_dox_threats.search(norm_content) or self.re_dox_threats.search(content) or self.re_dox_threats.search(collapsed)
        match_phone = self.re_phone.search(content)
        match_ip = self.re_ip.search(content)
        if match_dox or match_phone or match_ip:
            trigger = match_dox.group(0) if match_dox else (match_phone.group(0) if match_phone else match_ip.group(0))
            violations.append(RuleViolation(
                rule_code="п:5.0",
                rule_name="Личная информация (Доксинг)",
                category="Сливы / Деанон / Личные данные",
                severity="critical",
                matched_word=trigger,
                details="Распространение личных данных, сливы или угрозы деаноном/доксингом."
            ))

        # 7. NSFW / NSFL контент (п:6.0)
        match_nsfw = self.re_nsfw.search(norm_content) or self.re_nsfw.search(content) or self.re_nsfw.search(collapsed)
        if match_nsfw:
            violations.append(RuleViolation(
                rule_code="п:6.0",
                rule_name="Контент 18+ (NSFW/NSFL)",
                category="Запрещенный контент",
                severity="high",
                matched_word=match_nsfw.group(0),
                details="Упоминание или публикация NSFW/NSFL материалов."
            ))

        # 8. Выдача себя за администрацию (п:12.0)
        match_imp = self.re_impersonation.search(norm_content) or self.re_impersonation.search(content)
        if match_imp:
            violations.append(RuleViolation(
                rule_code="п:12.0",
                rule_name="Выдача себя за других",
                category="Администрация",
                severity="medium",
                matched_word=match_imp.group(0),
                details="Выдача себя за администрацию или модерацию сервера."
            ))

        # 9. Угрозы и насилие (п:14.0)
        match_threat = self.re_threats.search(norm_content) or self.re_threats.search(content)
        if match_threat:
            violations.append(RuleViolation(
                rule_code="п:14.0",
                rule_name="Угрозы и опасные действия",
                category="Прямые угрозы",
                severity="critical",
                matched_word=match_threat.group(0),
                details="Прямые угрозы насилием, расправой или причинением вреда."
            ))

        # 10. Фишинг / Скам (п:15.0)
        match_phish = self.re_phishing.search(content)
        if match_phish:
            violations.append(RuleViolation(
                rule_code="п:15.0",
                rule_name="Обман участников / Фишинг",
                category="Мошенничество",
                severity="critical",
                matched_word=match_phish.group(0),
                details="Подозрительная фишинговая ссылка (фейковый Nitro / Steam)."
            ))

        # 11. Реклама сторонних серверов / каналов (п:9.0)
        match_inv = self.re_invites.search(content)
        if match_inv:
            violations.append(RuleViolation(
                rule_code="п:9.0",
                rule_name="Реклама",
                category="Ссылки-приглашения",
                severity="medium",
                matched_word=match_inv.group(0),
                details="Ссылка-приглашение на сторонний сервер Discord или Telegram без разрешения."
            ))

        # 12. Шутки про трагедии / драмы (п:19.0)
        match_trag = self.re_tragedies.search(norm_content) or self.re_tragedies.search(content) or self.re_tragedies.search(collapsed)
        if match_trag:
            violations.append(RuleViolation(
                rule_code="п:19.0",
                rule_name="Шутки про трагедии/драмы",
                category="Трагедии / Драмы",
                severity="high",
                matched_word=match_trag.group(0),
                details="Упоминание/шутки на темы трагедий, массшутинга, казней или шок-мемов."
            ))

        # 13. Политика вне специального канала (п:8.0)
        if not is_politics_channel:
            match_pol = self.re_politics.search(norm_content) or self.re_politics.search(content) or self.re_politics.search(collapsed)
            if match_pol:
                violations.append(RuleViolation(
                    rule_code="п:8.0",
                    rule_name="Политика вне разрешенного канала",
                    category="Политические темы",
                    severity="medium",
                    matched_word=match_pol.group(0),
                    details=f"Обсуждение политики разрешено только в канале дискуссий. Текущий канал: #{channel_name}."
                ))

        # 14. Спам и флуд (п:10.0 и п:16.0)
        if not is_flood_channel:
            # Злоупотребление упоминаниями (п:16.0)
            if has_everyone or mentions_count >= 5:
                violations.append(RuleViolation(
                    rule_code="п:16.0",
                    rule_name="Злоупотребление упоминаниями",
                    category="Массовый пинг",
                    severity="high",
                    matched_word="@everyone/@here" if has_everyone else f"{mentions_count} упоминаний",
                    details="Массовые упоминания участников или использование @everyone/@here."
                ))

            # Повтор одного символа более 25 раз подряд (п:10.0)
            rep_match = re.search(r'(.)\1{24,}', content)
            if rep_match:
                violations.append(RuleViolation(
                    rule_code="п:10.0",
                    rule_name="Спам и флуд",
                    category="Повтор символов",
                    severity="low",
                    matched_word=rep_match.group(0)[:15] + "...",
                    details="Бессмысленный флуд повторяющимися символами."
                ))

            # Капс (> 75% заглавных букв при длине текста > 25 символов) (п:10.0)
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= 25:
                caps = [c for c in letters if c.isupper()]
                if len(caps) / len(letters) >= 0.75:
                    violations.append(RuleViolation(
                        rule_code="п:10.0",
                        rule_name="Спам и флуд",
                        category="Злоупотребление капсом",
                        severity="low",
                        matched_word="CAPSLOCK",
                        details="Более 75% сообщения написано заглавными буквами."
                    ))

            # Детектор флуда повторными сообщениями (п:10.0)
            now = time.time()
            user_history = self.user_message_history[author_id]
            user_history.append((now, content.strip()))
            self.user_message_history[author_id] = [(ts, msg) for ts, msg in user_history if now - ts < 20]

            recent = [msg for ts, msg in self.user_message_history[author_id]]
            if len(recent) >= 4 and len(set(recent[-4:])) == 1 and len(recent[-1]) > 2:
                violations.append(RuleViolation(
                    rule_code="п:10.0",
                    rule_name="Спам и флуд",
                    category="Повторяющиеся сообщения",
                    severity="medium",
                    matched_word=recent[-1][:20],
                    details="Отправка нескольких одинаковых сообщений подряд."
                ))

        return violations
