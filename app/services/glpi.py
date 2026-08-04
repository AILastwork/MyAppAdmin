from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests

from app.services.ad_directory import TRANSLIT, build_login_candidates, parse_full_name


DEFAULT_GLPI_BASE_URL = "http://glpi.osnova.local"
COMPUTER_LIST_PATH = "/front/computer.php"
REQUEST_TIMEOUT_SECONDS = 25


@dataclass(slots=True)
class GlpiComputer:
    glpi_id: str
    name: str = ""
    manufacturer: str = ""
    serial: str = ""
    type: str = ""
    model: str = ""
    modified: str = ""
    processor: str = ""
    mac: str = ""
    ip: str = ""
    disk: str = ""
    memory: str = ""
    memory_type: str = ""
    antivirus: str = ""
    os_name: str = ""
    os_version: str = ""
    last_boot: str = ""
    contact: str = ""
    url: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def ipv4_addresses(self) -> list[str]:
        return re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", self.ip)

    @property
    def mac_addresses(self) -> list[str]:
        return re.findall(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", self.mac.casefold())

    @property
    def display_ip(self) -> str:
        return " ".join(self.ipv4_addresses)


@dataclass(slots=True)
class GlpiSearchResult:
    computer: GlpiComputer
    score: int
    reason: str


@dataclass(slots=True)
class LoginForm:
    action: str
    fields: dict[str, str]
    login_field: str
    password_field: str
    remember_field: str = ""


class GlpiAuthenticationError(RuntimeError):
    pass


class GlpiParseError(RuntimeError):
    pass


class GlpiWebClient:
    def __init__(self, base_url: str = DEFAULT_GLPI_BASE_URL, session: requests.Session | None = None) -> None:
        self.base_url = normalize_base_url(base_url)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru,en;q=0.8",
            }
        )

    def login(self, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise ValueError("Введите логин и пароль GLPI.")

        login_url = urljoin(self.base_url, "/index.php") + "?" + urlencode({"redirect": COMPUTER_LIST_PATH})
        response = self.session.get(login_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        form = parse_login_form(response.text, response.url)

        payload = dict(form.fields)
        payload[form.login_field] = username.strip()
        payload[form.password_field] = password
        if form.remember_field:
            payload[form.remember_field] = payload.get(form.remember_field) or "on"
        payload.setdefault("submit", "Отправить")

        auth_response = self.session.post(
            form.action,
            data=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        auth_response.raise_for_status()

        check_response = self.session.get(
            self._computer_url(start=0),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        check_response.raise_for_status()
        if is_login_page(check_response.text, check_response.url):
            raise GlpiAuthenticationError("GLPI не принял логин или пароль.")

    def load_computers(self, on_status: Callable[[str], None] | None = None) -> list[GlpiComputer]:
        computers: list[GlpiComputer] = []
        seen_ids: set[str] = set()
        start = 0
        total = None

        while True:
            if on_status:
                on_status(f"Загружаю GLPI: стартовая строка {start + 1}...")

            response = self.session.get(self._computer_url(start=start), timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            if is_login_page(response.text, response.url):
                raise GlpiAuthenticationError("Сессия GLPI не активна. Выполните вход заново.")

            page_computers = parse_computer_list(response.text, self.base_url)
            page_info = parse_pager(response.text)

            for computer in page_computers:
                if computer.glpi_id and computer.glpi_id not in seen_ids:
                    seen_ids.add(computer.glpi_id)
                    computers.append(computer)

            if page_info:
                _from, to, total = page_info
                if on_status:
                    on_status(f"Загружено {min(to, total)} из {total} компьютеров...")
                if to >= total:
                    break
                if to <= start:
                    break
                start = to
                continue

            if not page_computers:
                break
            break

        return computers

    def _computer_url(self, *, start: int) -> str:
        params = [
            ("sort", "1"),
            ("order", "ASC"),
            ("criteria[0][field]", "view"),
            ("criteria[0][link]", "contains"),
            ("criteria[0][value]", ""),
            ("start", str(start)),
        ]
        return urljoin(self.base_url, COMPUTER_LIST_PATH) + "?" + urlencode(params)


def normalize_base_url(value: str) -> str:
    text = (value or DEFAULT_GLPI_BASE_URL).strip().rstrip("/")
    if not text:
        return DEFAULT_GLPI_BASE_URL
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    return text.rstrip("/")


def parse_login_form(html: str, current_url: str) -> LoginForm:
    parser = _LoginFormParser(current_url)
    parser.feed(html or "")
    if not parser.forms:
        raise GlpiParseError("На странице GLPI не найдена форма входа.")

    form = next((item for item in parser.forms if "login.php" in item["action"]), parser.forms[0])
    fields = dict(form["fields"])
    login_field = form.get("login_field", "")
    password_field = form.get("password_field", "")
    remember_field = form.get("remember_field", "")

    if not login_field or not password_field:
        raise GlpiParseError("Не удалось определить поля логина и пароля GLPI.")

    return LoginForm(
        action=form["action"],
        fields=fields,
        login_field=login_field,
        password_field=password_field,
        remember_field=remember_field,
    )


def parse_computer_list(html: str, base_url: str = DEFAULT_GLPI_BASE_URL) -> list[GlpiComputer]:
    parser = _ComputerTableParser(normalize_base_url(base_url))
    parser.feed(html or "")
    return parser.computers


def parse_pager(html: str) -> tuple[int, int, int] | None:
    text = html_to_text(html)
    match = re.search(r"С\s+(\d+)\s+по\s+(\d+)\s+из\s+(\d+)", text, flags=re.I)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_login_page(html: str, url: str = "") -> bool:
    lowered = (html or "").casefold()
    return (
        "glpi - аутентификация" in lowered
        or "id=\"login_name\"" in lowered
        or "id='login_name'" in lowered
        or "/front/login.php" in (url or "").casefold()
    )


def search_computers(computers: list[GlpiComputer], query: str) -> list[GlpiSearchResult]:
    terms = build_search_terms(query)
    if not terms:
        return [GlpiSearchResult(computer, 1, "весь загруженный список") for computer in computers]

    results: list[GlpiSearchResult] = []
    for computer in computers:
        score, reason = _score_computer(computer, terms)
        if score > 0:
            results.append(GlpiSearchResult(computer, score, reason))

    return sorted(results, key=lambda item: (-item.score, item.computer.name.casefold()))


def build_search_terms(query: str) -> set[str]:
    raw = normalize_search_text(query)
    if not raw:
        return set()

    terms = {raw}
    if "@" in raw:
        terms.add(raw.split("@", 1)[0])

    tokens = [token for token in re.split(r"[\s,;]+", query.strip()) if token]
    transliterated_tokens = [_translit_fragment(token) for token in tokens]
    terms.update(token for token in transliterated_tokens if len(token) >= 2)

    if len(tokens) >= 2:
        last_name, first_name, middle_name = parse_full_name(query)
        terms.update(build_login_candidates(last_name, first_name, middle_name))

        swapped_middle = " ".join(tokens[2:])
        terms.update(build_login_candidates(tokens[1], tokens[0], swapped_middle))
        terms.update(_partial_login_terms(transliterated_tokens))
    elif len(transliterated_tokens) == 1:
        token = transliterated_tokens[0]
        if len(token) >= 3:
            terms.add(token)
            terms.add(f"{token[0]}.")

    return {normalize_search_text(term) for term in terms if normalize_search_text(term)}


def normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def html_to_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _score_computer(computer: GlpiComputer, terms: set[str]) -> tuple[int, str]:
    haystacks = {
        "имя компьютера": computer.name,
        "пользователь": computer.contact,
        "IP": computer.ip,
        "MAC": computer.mac,
        "серийный номер": computer.serial,
        "модель": computer.model,
        "процессор": computer.processor,
    }
    best_score = 0
    best_reason = ""

    for term in terms:
        for label, value in haystacks.items():
            normalized = normalize_search_text(value)
            if not normalized:
                continue
            score = 0
            if label == "имя компьютера" and term == normalized:
                score = 120
            elif label == "пользователь":
                score = _score_contact(normalized, term)
            elif label == "имя компьютера" and term in normalized:
                score = 95
            elif label in {"IP", "MAC", "серийный номер"} and term in normalized:
                score = 85
            elif term in normalized:
                score = 60

            if score > best_score:
                best_score = score
                best_reason = f"{label}: {value}"

    return best_score, best_reason


def _score_contact(contact: str, term: str) -> int:
    login_part = contact.split("@", 1)[0]
    if login_part and term == login_part:
        return 115
    if len(term) >= 3 and term in contact:
        return 105
    if term.endswith(".") and len(term) == 2 and login_part.startswith(term):
        return 55
    return 0


def _partial_login_terms(tokens: list[str]) -> set[str]:
    clean_tokens = [token for token in tokens if token]
    if len(clean_tokens) < 2:
        return set()

    result: set[str] = set()
    first, second = clean_tokens[0], clean_tokens[1]
    for first_name, last_name in ((first, second), (second, first)):
        if first_name and last_name:
            result.add(f"{first_name[0]}.{last_name}")
            result.add(f"{first_name}.{last_name}")
    return result


def _translit_fragment(value: str) -> str:
    result = []
    for char in (value or "").casefold():
        if char in TRANSLIT:
            result.append(TRANSLIT[char])
        elif char.isascii() and (char.isalnum() or char in "._-"):
            result.append(char)
    return re.sub(r"[^a-z0-9._-]+", "", "".join(result))


class _LoginFormParser(HTMLParser):
    def __init__(self, current_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.current_url = current_url
        self.forms: list[dict[str, object]] = []
        self._current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.casefold(): value or "" for name, value in attrs}
        if tag.casefold() == "form":
            self._current = {
                "action": urljoin(self.current_url, attr.get("action", "")),
                "fields": {},
                "login_field": "",
                "password_field": "",
                "remember_field": "",
            }
            return

        if self._current is None or tag.casefold() != "input":
            return

        name = attr.get("name", "")
        if not name:
            return
        input_id = attr.get("id", "")
        input_type = attr.get("type", "text").casefold()
        value = attr.get("value", "")
        fields = self._current["fields"]
        assert isinstance(fields, dict)
        fields[name] = value
        if input_id == "login_name":
            self._current["login_field"] = name
        elif input_id == "login_password" or input_type == "password":
            self._current["password_field"] = name
        elif input_id == "login_remember":
            self._current["remember_field"] = name

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


class _ComputerTableParser(HTMLParser):
    HEADER_TO_FIELD = {
        "Наименование": "name",
        "Производитель": "manufacturer",
        "Серийный номер": "serial",
        "Тип": "type",
        "Модель": "model",
        "Последнее изменение": "modified",
        "Компоненты - Процессор": "processor",
        "Сетевая структура - MAC-адрес": "mac",
        "Сетевая структура - IP": "ip",
        "Компоненты - Тип HDD": "disk",
        "Компоненты - Память": "memory",
        "Компоненты - Тип памяти": "memory_type",
        "Антивирусы - Наименование": "antivirus",
        "Операционная система - Наименование": "os_name",
        "Операционная система - Версия": "os_version",
        "Плагины - FusInv - Last boot": "last_boot",
        "Контактное лицо": "contact",
    }

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.computers: list[GlpiComputer] = []
        self.headers: list[str] = []
        self._in_table = False
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._row_cells: list[str] = []
        self._cell_parts: list[str] = []
        self._row_computer_id = ""
        self._row_computer_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.casefold(): value or "" for name, value in attrs}
        tag = tag.casefold()

        if tag == "table" and "tab_cadrehov" in attr.get("class", ""):
            self._in_table = True
            self._table_depth = 1
            return

        if not self._in_table:
            return

        if tag == "table":
            self._table_depth += 1
        elif tag == "tr":
            self._in_row = True
            self._row_cells = []
            self._row_computer_id = ""
            self._row_computer_url = ""
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_cell:
            href = attr.get("href", "")
            if "computer.form.php" in href:
                self._row_computer_url = urljoin(self.base_url, href)
                parsed = urlparse(self._row_computer_url)
                self._row_computer_id = parse_qs(parsed.query).get("id", [""])[0]

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if not self._in_table:
            return

        if tag in {"td", "th"} and self._in_cell:
            self._row_cells.append(_clean_cell_text(" ".join(self._cell_parts)))
            self._in_cell = False
            self._cell_parts = []
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_table = False

    def _finish_row(self) -> None:
        cells = [cell for cell in self._row_cells if cell and "shiftSelectable" not in cell]
        if not cells:
            return

        if not self.headers and "Наименование" in cells and "Производитель" in cells:
            self.headers = [cell for cell in cells if cell in self.HEADER_TO_FIELD]
            return

        if not self._row_computer_id or not self.headers:
            return

        values = list(cells)
        if len(values) == len(self.headers) + 1:
            values = values[1:]
        if len(values) < len(self.headers):
            return

        raw = dict(zip(self.headers, values, strict=False))
        kwargs = {
            field_name: raw.get(header, "")
            for header, field_name in self.HEADER_TO_FIELD.items()
        }
        self.computers.append(
            GlpiComputer(
                glpi_id=self._row_computer_id,
                url=self._row_computer_url,
                raw=raw,
                **kwargs,
            )
        )


def _clean_cell_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()
