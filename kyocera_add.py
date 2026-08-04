# ============================================================
# FINAL v13: Kyocera Command Center RX Address Book Automation
#
# Исправление v13:
#   - поддержка DeepSleep.html помимо DeepSleep.htm;
#   - пробуждение через /esu/set.cgi теперь пробует HTTP и HTTPS;
#   - добавлен payload без submit001 на случай, если прошивка проверяет только func=wakeup;
#   - исправлено для ECOSYS M3540idn / host KM2E4BF8.
# ============================================================

from __future__ import annotations

import argparse
import html
import re
import ssl
import sys
import time
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, parse_qsl, urlencode, urlparse, urlunparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# НАСТРОЙКИ
# ============================================================

PRINTER_URL = "http://10.14.27.10"

KYOCERA_ADMIN_LOGIN = "Admin"
KYOCERA_ADMIN_PASSWORD = ""

SMB_HOST = "osnova.local"
SMB_PORT = "445"
SMB_USERNAME = r"osnova.local\scan_user"
SMB_PASSWORD = ""

SMB_BASE_PATH = r"fs\userfolder"
SMB_SCAN_SUBFOLDER = "scan"

CONTACT_FULL_NAME = "Никитин Анатолий Сергеевич"
CONTACT_LOGIN = "a.nikitin"
CONTACT_EMAIL = "a.nikitin@mkd-osnova.ru"

# Пусто = взять первый свободный номер автоматически
CONTACT_NUMBER = ""

TIMEOUT = 10
ADD_CONTACT_TIMEOUT_SECONDS = 35
POST_COMMIT_VERIFY_DELAY_SECONDS = 4
PRINTER_PREFLIGHT_TIMEOUT_SECONDS = 10
PRINTER_PREFLIGHT_CONNECT_TIMEOUT_SECONDS = 2


# Это оригинальный POST body логина, снятый из captured_requests.json.
# В нём сохранён порядок полей и дублирующиеся поля, как у браузера.
RAW_LOGIN_BODY_TEMPLATE = 'failhtmfile=%2Fstartwlm%2FStart_Wlm.htm&okhtmfile=%2Fstartwlm%2FStart_Wlm.htm&func=authLogin&arg03_LoginType=_mode_off&arg04_LoginFrom=_wlm_login&hidden=&language=http%3A%2F%2F10.14.32.40%2Fwlmpor%2Findex.htm&hiddRefreshDevice=..%2Fstartwlm%2FHme_DvcSts.htm&hiddRefreshPanelUsed=..%2Fstartwlm%2FHme_PnlUsg.htm&hiddRefreshPaperid=..%2Fstartwlm%2FHme_Paper.htm&hiddRefreshTonerid=..%2Fstartwlm%2FHme_StplPnch.htm&hiddRefreshStapleid=..%2Fstartwlm%2FHme_Toner.htm&hiddnBackNavIndx=1&hiddRefreshDeviceBack=&hiddRefreshPanelUsedBack=&hiddRefreshPaperidBack=&hiddRefreshToneridBack=&hiddRefreshStapleidBack=&hiddCompatibility=&hiddPasswordToOpenChk=&hiddPasswordToOpen=&hiddRePasswordToOpen=&hiddPasswordToEditChk=&hiddPasswordToEdit=&hiddRePasswordToEdit=&hiddPrinting=&hiddChanges=&hiddCopyingOfText=&hiddEmaiSID=&hiddFAXNumber=&hiddAddrFAXNumber=&hiddEmaiName=&hiddECM=&hiddDocID=&privid=&publicid=&attrtype=&attrname=&hiddFolderType=&hiddFolderSMBType=&hiddFolderFTPType=&hiddSMBNumber1=&hiddSMBNumber2=&hiddSMBNumber3=&hiddSMBNumber4=&hiddSMBNumber5=&hiddSMBNumber6=&hiddSMBNumber7=&hiddFTPNumber1=&hiddFTPNumber2=&hiddFTPNumber3=&hiddFTPNumber4=&hiddFTPNumber5=&hiddFTPNumber6=&hiddFTPNumber7=&hiddFAXAddress1=&hiddFAXAddress2=&hiddFAXAddress3=&hiddFAXAddress4=&hiddFAXAddress5=&hiddFAXAddress6=&hiddFAXAddress7=&hiddFAXAddress8=&hiddFAXAddress9=&hiddFAXAddress10=&hiddIFaxAdd=&hiddIFaxViaServer=&hiddIFaxConnMode=&hiddIFaxResolution=&hiddIFaxResolution1=&hiddIFaxResolution2=&hiddIFaxResolution3=&hiddIFaxResolution4=&hiddIFaxResolution5=&hiddIFaxComplession=&hiddIFaxPaperSize=&hiddIFaxPaperSize1=&hiddIFaxPaperSize2=&hiddIFaxPaperSize3=&hiddImage=&hiddTest=&hiddDoc_Num=&hiddCopy=&hiddDocument=&hiddDocRec=&AddressNumberPersonal=&AddressNumberGroup=&hiddPersonAddressID=&hiddGroupAddressID=&hiddPrnBasic=&hiddPageName=&hiddDwnLoadType=&hiddPrintType=&hiddSend1=&hiddSend2=&hiddSend3=&hiddSend4=&hiddSend5=&hiddAddrBokBackUrl=&hiddAddrBokNumber=&hiddAddrBokName=&hiddAddrBokFname=&hiddSendFileName=&hiddenAddressbook=&hiddenAddressbook1=&hiddSendDoc_Num=&hiddSendColor=&hiddSendAddInfo=&hiddSendFileFormat=&hiddMoveConfScn=&hiddRefreshDevice=..%2Fstartwlm%2FHme_DvcSts.htm&hiddRefreshPanelUsed=..%2Fstartwlm%2FHme_PnlUsg.htm&hiddRefreshPaperid=..%2Fstartwlm%2FHme_Paper.htm&hiddRefreshTonerid=..%2Fstartwlm%2FHme_StplPnch.htm&hiddRefreshStapleid=..%2Fstartwlm%2FHme_Toner.htm&hiddnBackNavIndx=1&hiddRefreshDeviceBack=&hiddRefreshPanelUsedBack=&hiddRefreshPaperidBack=&hiddRefreshToneridBack=&hiddRefreshStapleidBack=&hiddValue=&arg01_UserName=Admin&arg02_Password=Admin&arg03_LoginType=_mode_off&arg05_AccountId=&Login=%D0%92%D1%85%D0%BE%D0%B4+%D0%B2+%D1%81%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D1%83&arg06_DomainName=&hndHeight=0'


@dataclass
class KyoceraContact:
    number: str
    name: str
    email: str
    smb_host: str
    smb_port: str
    smb_path: str
    smb_username: str
    smb_password: str


@dataclass
class ContactFormProfile:
    action_url: str
    default_fields: list[tuple[str, str]]


def log(message: str) -> None:
    print(f"[KYOCERA] {message}", flush=True)


def base_url() -> str:
    return PRINTER_URL.rstrip("/") + "/"


def normalize_printer_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    if not url:
        raise ValueError("Не указан адрес принтера.")
    if not url.lower().startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


def make_url(path: str) -> str:
    return urljoin(base_url(), path.lstrip("/"))


def is_unified_ews_response(text: str) -> bool:
    lowered = (text or "").casefold()
    return (
        "/framework/unified.js" in lowered
        or 'frameworkobj.pkg = "ews"' in lowered
        or "pgm-overall-container" in lowered
    )


def discover_printer_base_url(session: requests.Session) -> str:
    global PRINTER_URL

    initial_url = base_url()
    log(f"Определяю рабочий URL принтера: {initial_url}")
    log("Проверка сертификата Command Center RX отключена: предупреждение безопасности будет принято автоматически.")
    try:
        response = session.get(
            initial_url,
            headers={
                "User-Agent": session.headers["User-Agent"],
                "Accept-Encoding": "identity",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError as exc:
        log(f"Стандартный TLS не принят устройством: {exc}")
        log("Включаю совместимый TLS-режим для старой прошивки и продолжаю.")
        enable_legacy_tls_compatibility(session)
        response = session.get(
            initial_url,
            headers={
                "User-Agent": session.headers["User-Agent"],
                "Accept-Encoding": "identity",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Стартовая страница принтера вернула HTTP {response.status_code}.")

    if is_unified_ews_response(getattr(response, "text", "")):
        raise RuntimeError(
            "Обнаружен новый Kyocera Unified/EWS интерфейс. "
            "Текущий сценарий добавления адресной книги поддерживает Command Center RX/WLM "
            "(/startwlm/login.cgi и /basic/set.cgi). Для этого принтера нужен отдельный EWS-адаптер."
        )

    parsed = urlparse(response.url)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"Принтер вернул некорректный URL: {response.url}")
    PRINTER_URL = f"{parsed.scheme}://{parsed.netloc}"
    log(f"Рабочий URL принтера: {PRINTER_URL}")
    if parsed.scheme.lower() == "https":
        log("Принтер использует HTTPS-профиль Command Center RX.")
    return PRINTER_URL


def absolute_url(referer_url: str, href: str) -> str:
    """
    Делает абсолютный URL из src/href.
    Нужен для разных прошивок Kyocera, где script src может быть ./js, ../js или /js.
    """
    if not href:
        return ""

    parsed = urlparse(href)
    if parsed.scheme and parsed.netloc:
        return href

    return urljoin(referer_url, href)


def save_text_debug(text: str, filename: str) -> None:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
        log(f"Текст сохранён: {filename}")
    except Exception as exc:
        log(f"Не удалось сохранить {filename}: {exc}")


def extract_script_urls(html: str, referer_url: str, name_filter: str = "") -> list[str]:
    urls: list[str] = []

    for match in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.I):
        src = match.group(1).replace("&amp;", "&")
        if name_filter and name_filter.lower() not in src.lower():
            continue
        full = absolute_url(referer_url, src)
        if full and full not in urls:
            urls.append(full)

    return urls


def get_with_debug(
    session: requests.Session,
    url: str,
    referer: str,
    label: str,
) -> requests.Response:
    r = session.get(
        url,
        headers={
            "Referer": referer,
            "User-Agent": session.headers["User-Agent"],
            "Accept-Encoding": "identity",
        },
        timeout=TIMEOUT,
    )
    log(f"GET {label}: {url} -> HTTP {r.status_code}")
    if r.status_code >= 400:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label)
        save_response_debug(r, f"kyocera_{safe}_error.html")
    return r


def build_smb_path(login: str) -> str:
    return rf"{SMB_BASE_PATH}\{login.strip()}\{SMB_SCAN_SUBFOLDER}"


def make_short_name(full_name: str) -> str:
    """
    Никитин Анатолий Сергеевич -> Никитин А.С.

    Финальная точка оставлена: так обычно отображается имя в адресной книге Kyocera.
    Старые модели принимают и вариант без последней точки.
    """
    parts = full_name.strip().split()

    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0].upper()}.{parts[2][0].upper()}."

    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0].upper()}."

    return full_name.strip()


def regex_first(pattern: str, text: str, default: str = "") -> str:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1) if m else default


def parse_empty_memory_id(model_text: str) -> str:
    value = regex_first(r"_pp\.emptyMemoryId\s*=\s*'([^']*)'", model_text)

    if not value:
        raise RuntimeError("Не найден _pp.emptyMemoryId в модели формы добавления контакта.")

    first_id = value.split("/")[0].strip()

    if not re.fullmatch(r"\d{3}", first_id):
        raise RuntimeError(f"Первый свободный номер выглядит некорректно: {first_id!r}")

    return first_id


def parse_hidden_value(text: str) -> str:
    for pattern in [
        r"_pp\.hiddenvalue\s*=\s*'([^']*)'",
        r'name=["\']hidden["\']\s+value=["\']([^"\']*)["\']',
        r'value=["\']([^"\']*)["\']\s+[^>]*name=["\']hidden["\']',
    ]:
        value = regex_first(pattern, text)
        if value:
            return value

    # В ваших снятых HTML/model это значение было 1687199710.
    log("hidden value не найден, использую fallback 1687199710")
    return "1687199710"



# ============================================================
# WAKE / ENERGY SAVER
# ============================================================

ENERGY_SAVER_TIMEOUT_SECONDS = 45
ENERGY_SAVER_RETRY_SECONDS = 5


def is_energy_saver_response(text: str) -> bool:
    """
    Строгая проверка страницы энергосбережения Kyocera.

    v13:
    - добавлена поддержка DeepSleep.html, потому что на ECOSYS M3540idn
      сохранённая страница показывает frame src="./10.14.32.34_files/DeepSleep.html".
    - не используем общие слова вроде sleep/energy saver отдельно, чтобы не ломать login.
    """
    t = (text or "").lower()

    if not t:
        return False

    strict_patterns = [
        r'<frame[^>]+src=["\'][^"\']*deepsleep\.(?:htm|html)',
        r'id=["\']deepsleepset["\']',
        r'action=["\']/esu/set\.cgi["\']',
        r'name=["\']func["\'][^>]+value=["\']wakeup["\']',
        r'value=["\']wakeup["\'][^>]+name=["\']func["\']',
    ]

    for item_pattern in strict_patterns:
        if re.search(item_pattern, t, flags=re.I | re.S):
            return True

    if "/esu/set.cgi" in t and "wakeup" in t and ("deepsleep" in t or "okhtmfile" in t):
        return True

    if (
        "аппарат в режиме энергосбережения" in t
        and "чтобы воспользоваться программой" in t
        and ("старт" in t or "пуск" in t)
    ):
        return True

    if (
        "now, the machine is in the energy saver mode" in t
        and "click [start] to use the program" in t
    ):
        return True

    return False

    strict_patterns = [
        r'<frame[^>]+src=["\']?deepsleep\.htm',
        r'id=["\']deepsleepset["\']',
        r'action=["\']/esu/set\.cgi["\']',
        r'name=["\']func["\'][^>]+value=["\']wakeup["\']',
        r'value=["\']wakeup["\'][^>]+name=["\']func["\']',
    ]

    for pattern in strict_patterns:
        if re.search(pattern, t, flags=re.I | re.S):
            return True

    if "/esu/set.cgi" in t and "wakeup" in t and ("deepsleep" in t or "okhtmfile" in t):
        return True

    # Видимый русский текст именно DeepSleep страницы.
    if (
        "аппарат в режиме энергосбережения" in t
        and "чтобы воспользоваться программой" in t
        and ("старт" in t or "пуск" in t)
    ):
        return True

    # Видимый английский текст именно DeepSleep страницы.
    if (
        "now, the machine is in the energy saver mode" in t
        and "click [start] to use the program" in t
    ):
        return True

    return False





def absolute_action_url(current_url: str, action: str) -> str:
    """
    Делает абсолютный URL для action формы.
    """
    if not action:
        return current_url

    if action.startswith("http://") or action.startswith("https://"):
        return action

    return urljoin(current_url, action)


def extract_input_fields(form_html: str) -> list[tuple[str, str]]:
    """
    Мини-парсер input/select/textarea без внешних зависимостей.
    Нужен для старых HTML-страниц Kyocera.
    """
    fields: list[tuple[str, str]] = []

    for tag in re.findall(r"<input\b[^>]*>", form_html or "", flags=re.I | re.S):
        name = regex_first(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", tag)
        if not name:
            continue

        value = regex_first(r"\bvalue\s*=\s*['\"]([^'\"]*)['\"]", tag)
        input_type = regex_first(r"\btype\s*=\s*['\"]([^'\"]+)['\"]", tag).lower()

        # checkbox/radio без checked не отправляем.
        if input_type in {"checkbox", "radio"} and not re.search(r"\bchecked\b", tag, flags=re.I):
            continue

        fields.append((name, value))

    for tag in re.findall(r"<textarea\b[^>]*>[\s\S]*?</textarea>", form_html or "", flags=re.I):
        name = regex_first(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", tag)
        value = re.sub(r"^.*?>|</textarea>.*$", "", tag, flags=re.I | re.S)
        if name:
            fields.append((name, value))

    # select: берём selected option или первую option.
    for select in re.findall(r"<select\b[^>]*>[\s\S]*?</select>", form_html or "", flags=re.I):
        name = regex_first(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", select)
        if not name:
            continue

        selected = re.search(
            r"<option\b[^>]*\bselected\b[^>]*value\s*=\s*['\"]([^'\"]*)['\"]",
            select,
            flags=re.I | re.S,
        )
        if selected:
            fields.append((name, selected.group(1)))
            continue

        first = re.search(
            r"<option\b[^>]*value\s*=\s*['\"]([^'\"]*)['\"]",
            select,
            flags=re.I | re.S,
        )
        if first:
            fields.append((name, first.group(1)))

    return fields


def find_energy_saver_forms(html: str) -> list[dict]:
    """
    Ищет формы/кнопки на странице энергосбережения.

    На разных Kyocera это может быть:
    - <form action="..." method="post"><input ...><input type=submit value="Пуск"></form>
    - <input type=button onclick="location.href='...'">
    - ссылка <a href="...">Пуск</a>
    """
    html = html or ""
    forms: list[dict] = []

    for form_html in re.findall(r"<form\b[^>]*>[\s\S]*?</form>", html, flags=re.I):
        action = regex_first(r"\baction\s*=\s*['\"]([^'\"]*)['\"]", form_html)
        method = regex_first(r"\bmethod\s*=\s*['\"]([^'\"]*)['\"]", form_html, "get").lower()
        text_plain = strip_html(form_html).lower()

        # Берём формы, которые явно похожи на пробуждение/старт,
        # либо если вся страница EnergySaver, берём все небольшие формы.
        looks_like_wake = any(x in text_plain for x in [
            "пуск",
            "start",
            "wake",
            "sleep",
            "энергосбереж",
            "deepsleep",
        ])

        fields = extract_input_fields(form_html)

        if looks_like_wake or fields:
            forms.append({
                "kind": "form",
                "action": action,
                "method": method,
                "fields": fields,
                "preview": text_plain[:300],
            })

    # Ссылки с текстом Пуск / Start / Wake
    for m in re.finditer(r"<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>([\s\S]*?)</a>", html, flags=re.I):
        href = m.group(1)
        label = strip_html(m.group(2)).lower()

        if any(x in label for x in ["пуск", "start", "wake", "продолж"]):
            forms.append({
                "kind": "link",
                "action": href,
                "method": "get",
                "fields": [],
                "preview": label[:300],
            })

    # onclick location.href='...'
    for m in re.finditer(
        r"onclick\s*=\s*['\"][^'\"]*(?:location\.href|window\.location)\s*=\s*['\"]([^'\"]+)['\"]",
        html,
        flags=re.I,
    ):
        forms.append({
            "kind": "onclick",
            "action": m.group(1),
            "method": "get",
            "fields": [],
            "preview": "onclick location",
        })

    return forms



def switch_scheme(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    if url.startswith("https://"):
        return "http://" + url[len("https://"):]
    return url


def unique_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    for url in urls:
        if url and url not in result:
            result.append(url)
    return result


def extract_deepsleep_frame_urls(current_url: str, html: str) -> list[str]:
    """
    Ищет DeepSleep frame/src.
    Поддерживает:
    - src="DeepSleep.htm"
    - src="DeepSleep.html"
    - src="./10.14.32.34_files/DeepSleep.html" в сохранённом HTML
    """
    urls: list[str] = []

    for match in re.finditer(r'<(?:frame|iframe)[^>]+src=["\']([^"\']*deepsleep\.(?:htm|html))["\']', html or "", flags=re.I):
        src = match.group(1)
        # Если это браузерно-сохранённый путь вида ./10.14.32.34_files/DeepSleep.html,
        # на реальном устройстве его нет. В таком случае дополнительно пробуем /DeepSleep.htm и /DeepSleep.html.
        urls.append(urljoin(current_url, src))

    urls.append(urljoin(current_url, "DeepSleep.htm"))
    urls.append(urljoin(current_url, "DeepSleep.html"))
    urls.append(urljoin(PRINTER_URL.rstrip("/") + "/", "DeepSleep.htm"))
    urls.append(urljoin(PRINTER_URL.rstrip("/") + "/", "DeepSleep.html"))

    # Если пользователь указал http, а реальная страница была открыта через https,
    # пробуем альтернативную схему только для wake-up.
    expanded: list[str] = []
    for url in urls:
        expanded.append(url)
        expanded.append(switch_scheme(url))

    return unique_urls(expanded)


def extract_wakeup_action_urls(current_url: str, html: str) -> list[str]:
    urls: list[str] = []

    for match in re.finditer(r'<form[^>]*action=["\']([^"\']*esu/set\.cgi[^"\']*)["\']', html or "", flags=re.I):
        urls.append(urljoin(current_url, match.group(1)))

    urls.append(urljoin(current_url, "/esu/set.cgi"))
    urls.append(urljoin(PRINTER_URL.rstrip("/") + "/", "/esu/set.cgi"))

    expanded: list[str] = []
    for url in urls:
        expanded.append(url)
        expanded.append(switch_scheme(url))

    return unique_urls(expanded)


def try_kyocera_deepsleep_wakeup(session: requests.Session, current_url: str, html: str) -> bool:
    """
    Точное пробуждение для Kyocera DeepSleep.

    Диагностика показала:
    - корень содержит frame на DeepSleep.htm / DeepSleep.html;
    - внутри есть форма:
        action="/esu/set.cgi"
        method="post"
        okhtmfile=DeepSleepApply.htm
        func=wakeup
        submit001=Пуск

    v13:
    - поддерживает DeepSleep.htm и DeepSleep.html;
    - пробует HTTP и HTTPS для wake-up;
    - пробует несколько payload-вариантов.
    """
    lower_html = (html or "").lower()
    deep_html = html or ""
    deep_url_used = current_url

    # Если корень — frameset, дочитываем DeepSleep frame.
    if "deepsleep.htm" in lower_html or "deepsleep.html" in lower_html:
        for deep_url in extract_deepsleep_frame_urls(current_url, html):
            try:
                log(f"Пробую открыть страницу сна: {deep_url}")

                r_deep = session.get(
                    deep_url,
                    headers={
                        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                        "Accept-Encoding": "identity",
                        "Referer": current_url,
                        "Connection": "close",
                    },
                    timeout=10,
                    allow_redirects=False,
                    verify=False,
                )

                log(f"GET DeepSleep candidate -> HTTP {r_deep.status_code}")

                if r_deep.status_code == 200 and (
                    "/esu/set.cgi" in (r_deep.text or "").lower()
                    or "wakeup" in (r_deep.text or "").lower()
                    or "deepsleepset" in (r_deep.text or "").lower()
                ):
                    deep_url_used = r_deep.url
                    deep_html = r_deep.text or ""
                    break

            except Exception as exc:
                log(f"Не удалось открыть DeepSleep candidate {deep_url}: {exc}")

    if not (
        "/esu/set.cgi" in (deep_html or "").lower()
        or "wakeup" in (deep_html or "").lower()
        or "deepsleepset" in (deep_html or "").lower()
    ):
        log("DeepSleep форма wakeup не найдена в HTML.")
        return False

    payload_variants = [
        [
            ("okhtmfile", "DeepSleepApply.htm"),
            ("func", "wakeup"),
            ("submit001", "Пуск"),
        ],
        [
            ("submit001", "Пуск"),
            ("okhtmfile", "DeepSleepApply.htm"),
            ("func", "wakeup"),
        ],
        [
            ("okhtmfile", "DeepSleepApply.htm"),
            ("func", "wakeup"),
            ("submit001", "Start"),
        ],
        [
            ("okhtmfile", "DeepSleepApply.htm"),
            ("func", "wakeup"),
        ],
    ]

    for wake_url in extract_wakeup_action_urls(deep_url_used, deep_html):
        for index, payload in enumerate(payload_variants, start=1):
            try:
                log(f"Пробую POST wakeup: {wake_url} payload#{index}")

                r = session.post(
                    wake_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": wake_url.split("/esu/set.cgi")[0],
                        "Referer": deep_url_used,
                        "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                    timeout=10,
                    allow_redirects=False,
                    verify=False,
                )

                log(f"POST wakeup -> HTTP {r.status_code}")

                if r.status_code in (200, 204, 302, 303):
                    return True

            except Exception as exc:
                log(f"POST wakeup не сработал: {wake_url}: {exc}")

    return False


def try_press_web_start_button(session: requests.Session, current_url: str, html: str) -> bool:
    """
    Пытается нажать веб-кнопку Пуск/Start на странице Energy Saver.

    Возвращает True, если удалось отправить какую-то форму/ссылку.
    Это не гарантирует, что аппарат физически проснулся, поэтому после этого
    всё равно вызывается wait_printer_ready().
    """
    forms = find_energy_saver_forms(html)

    if not forms:
        log("На странице энергосбережения не найдена HTML-кнопка/форма Пуск.")
        return False

    log(f"Найдено возможных веб-кнопок пробуждения: {len(forms)}")

    for idx, form in enumerate(forms, start=1):
        action_url = absolute_action_url(current_url, form.get("action", ""))
        method = (form.get("method") or "get").lower()
        fields = form.get("fields") or []

        try:
            log(
                f"Пробую нажать веб-Пуск #{idx}: "
                f"method={method.upper()} url={action_url} preview={form.get('preview', '')[:120]}"
            )

            headers = {
                "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                "Accept-Encoding": "identity",
                "Referer": current_url,
                "Connection": "close",
            }

            if method == "post":
                r = session.post(
                    action_url,
                    data=fields,
                    headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                    allow_redirects=False,
                )
            else:
                r = session.get(
                    action_url,
                    headers=headers,
                    timeout=10,
                    allow_redirects=False,
                )

            log(f"Веб-Пуск #{idx} -> HTTP {r.status_code}")

            # Любой ответ от кнопки считаем успешной попыткой.
            return True

        except Exception as exc:
            log(f"Веб-Пуск #{idx} не сработал: {exc}")

    return False

def tcp_port_open(host: str, port: int = 80, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def preflight_printer_availability() -> None:
    global PRINTER_URL

    parsed = urlparse(PRINTER_URL)
    host = parsed.hostname
    if not host:
        raise ValueError(f"Не удалось определить host принтера: {PRINTER_URL}")

    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Некорректный порт принтера: {PRINTER_URL}") from exc

    if explicit_port is not None:
        candidates = [(parsed.scheme.lower() or "http", explicit_port)]
    elif parsed.scheme.lower() == "https":
        candidates = [("https", 443), ("http", 80)]
    else:
        candidates = [("http", 80), ("https", 443)]

    ports_text = "/".join(str(port) for _scheme, port in candidates)
    log(
        f"Первичная проверка доступности {host} по TCP {ports_text} "
        f"(до {PRINTER_PREFLIGHT_TIMEOUT_SECONDS} сек)..."
    )
    deadline = time.monotonic() + PRINTER_PREFLIGHT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        for scheme, port in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connect_timeout = min(PRINTER_PREFLIGHT_CONNECT_TIMEOUT_SECONDS, remaining)
            if tcp_port_open(host, port, timeout=connect_timeout):
                if explicit_port is None:
                    PRINTER_URL = f"{scheme}://{host}"
                log(f"Принтер доступен по TCP {port}.")
                return
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))

    raise RuntimeError(
        f"Принтер {host} недоступен по TCP {ports_text}. "
        f"Проверка остановлена через {PRINTER_PREFLIGHT_TIMEOUT_SECONDS} сек. "
        "Проверьте IP, питание устройства, маршрут и правила межсетевого экрана."
    )


def printer_host_from_url(url: str) -> str:
    return urlparse(normalize_printer_url(url)).hostname or ""


def printer_port_from_url(url: str) -> int:
    parsed = urlparse(normalize_printer_url(url))
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme.lower() == "https" else 80


def wait_printer_ready(session: requests.Session, stage: str = "before_login") -> None:
    """
    Будит/ожидает Kyocera перед работой.

    Почему нужно:
    некоторые аппараты в энергосбережении возвращают DeepSleep-страницу,
    рвут соединение или отвечают 500/503. Если в этот момент сразу делать login/post,
    скрипт падает.

    Что делает:
    - каждые ENERGY_SAVER_RETRY_SECONDS секунд пробует GET /
    - если видит DeepSleep / Нажмите Пуск — ждёт дальше
    - если аппарат вообще не отвечает — ждёт дальше
    - если страница обычная HTTP 200 без DeepSleep — продолжает

    Если за timeout аппарат не проснулся, выдаёт понятное сообщение:
    нужно физически нажать кнопку Пуск/Старт на панели.
    """
    host = printer_host_from_url(PRINTER_URL)
    port = printer_port_from_url(PRINTER_URL)
    deadline = time.time() + ENERGY_SAVER_TIMEOUT_SECONDS
    attempt = 0
    last_error = ""

    log(f"Проверяю готовность принтера перед этапом {stage}...")

    while time.time() < deadline:
        attempt += 1

        if not tcp_port_open(host, port, timeout=2):
            last_error = f"TCP {port} не отвечает"
            log(
                f"Принтер пока не отвечает по TCP {port} "
                f"(попытка {attempt}). Жду {ENERGY_SAVER_RETRY_SECONDS} сек..."
            )
            time.sleep(ENERGY_SAVER_RETRY_SECONDS)
            continue

        try:
            r = session.get(
                make_url("/"),
                headers={
                    "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
                timeout=10,
            )

            body = r.text or ""

            if is_energy_saver_response(body):
                last_error = "аппарат в энергосбережении / DeepSleep"
                log("Принтер отвечает страницей энергосбережения.")

                # Сначала точная обработка Kyocera DeepSleep.htm:
                # POST /esu/set.cgi okhtmfile=DeepSleepApply.htm&func=wakeup&submit001=Пуск
                pressed = try_kyocera_deepsleep_wakeup(session, r.url, body)

                # Затем универсальная обработка HTML-форм/ссылок, если точный POST не помог.
                if not pressed:
                    pressed = try_press_web_start_button(session, r.url, body)

                if pressed:
                    log(
                        "Веб-кнопка Пуск/Start была нажата программно. "
                        f"Жду {ENERGY_SAVER_RETRY_SECONDS} сек и проверяю снова..."
                    )
                else:
                    log(
                        "Автоматически нажать веб-Пуск не удалось. "
                        "Если аппарат не проснётся, нажмите Пуск/Старт вручную на панели. "
                        f"Жду {ENERGY_SAVER_RETRY_SECONDS} сек..."
                    )

                time.sleep(ENERGY_SAVER_RETRY_SECONDS)
                continue

            if r.status_code in (200, 301, 302, 304, 401, 403):
                log(f"Принтер готов: GET / -> HTTP {r.status_code}")
                return

            last_error = f"HTTP {r.status_code}"
            log(
                f"Принтер ответил нестандартно: HTTP {r.status_code}. "
                f"Жду {ENERGY_SAVER_RETRY_SECONDS} сек..."
            )
            time.sleep(ENERGY_SAVER_RETRY_SECONDS)

        except Exception as exc:
            last_error = str(exc)
            log(
                f"Принтер ещё не готов или оборвал соединение: {exc}. "
                f"Жду {ENERGY_SAVER_RETRY_SECONDS} сек..."
            )
            time.sleep(ENERGY_SAVER_RETRY_SECONDS)

    raise RuntimeError(
        "Принтер не вышел из энергосбережения за "
        f"{ENERGY_SAVER_TIMEOUT_SECONDS} сек. Последняя ошибка: {last_error}. "
        "Скрипт попытался нажать веб-кнопку Пуск/Start, если она была найдена. "
        "Если пробуждение не произошло, нажмите Пуск/Старт на панели принтера "
        "или проверьте доступность устройства по сети."
    )


def safe_get_with_wake(
    session: requests.Session,
    url: str,
    *,
    headers: dict | None = None,
    timeout: int | None = None,
    stage: str = "GET",
    retries: int = 3,
    log_attempt_errors: bool = True,
) -> requests.Response:
    """
    GET с автоматическим повтором, если принтер спит или оборвал соединение.
    """
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=headers, timeout=timeout or TIMEOUT)

            if is_energy_saver_response(r.text):
                log(f"{stage}: принтер вернул DeepSleep/EnergySaver. Жду пробуждения...")
                wait_printer_ready(session, stage=stage)
                continue

            return r

        except Exception as exc:
            last_exc = exc
            if log_attempt_errors:
                log(f"{stage}: ошибка GET на попытке {attempt}/{retries}: {exc}")
            wait_printer_ready(session, stage=stage)

    raise RuntimeError(f"{stage}: GET не выполнен после {retries} попыток. Последняя ошибка: {last_exc}")


def safe_post_with_wake(
    session: requests.Session,
    url: str,
    *,
    data,
    headers: dict | None = None,
    timeout: int | None = None,
    allow_redirects: bool = False,
    stage: str = "POST",
    retries: int = 2,
) -> requests.Response:
    """
    POST с автоматическим повтором, если аппарат ушёл в сон до отправки запроса.

    Важно:
    для добавления контакта retries лучше держать 1-2, чтобы случайно не создать дубликат.
    """
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            r = session.post(
                url,
                data=data,
                headers=headers,
                timeout=timeout or TIMEOUT,
                allow_redirects=allow_redirects,
            )

            if is_energy_saver_response(r.text):
                log(f"{stage}: принтер вернул DeepSleep/EnergySaver. Жду пробуждения...")
                wait_printer_ready(session, stage=stage)
                continue

            return r

        except Exception as exc:
            last_exc = exc
            log(f"{stage}: ошибка POST на попытке {attempt}/{retries}: {exc}")
            wait_printer_ready(session, stage=stage)

    raise RuntimeError(f"{stage}: POST не выполнен после {retries} попыток. Последняя ошибка: {last_exc}")


def create_session() -> requests.Session:
    session = requests.Session()
    # Command Center RX обычно использует самоподписанный сертификат устройства.
    session.verify = False

    # Не задаём лишних заголовков на весь session.
    # У Kyocera старый сервер; чем ближе к HAR, тем лучше.
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        )
    })

    return session


class LegacyTlsAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "TLSVersion"):
            context.minimum_version = ssl.TLSVersion.TLSv1
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        pool_kwargs["ssl_context"] = context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def enable_legacy_tls_compatibility(session: requests.Session) -> None:
    session.verify = False
    session.mount("https://", LegacyTlsAdapter())


def save_response_debug(response: requests.Response, filename: str) -> None:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(response.text)
        log(f"Ответ сохранён: {filename}")
    except Exception as exc:
        log(f"Не удалось сохранить ответ {filename}: {exc}")


def build_raw_login_body() -> str:
    pairs = parse_qsl(RAW_LOGIN_BODY_TEMPLATE, keep_blank_values=True)

    result: list[tuple[str, str]] = []

    for key, value in pairs:
        if key == "arg01_UserName":
            value = KYOCERA_ADMIN_LOGIN
        elif key == "arg02_Password":
            value = KYOCERA_ADMIN_PASSWORD
        elif key == "language":
            value = make_url("/wlmpor/index.htm")

        result.append((key, value))

    return urlencode(result)


def login(session: requests.Session) -> None:
    """
    Логин максимально близко к captured_requests:
    POST http://10.14.32.40/startwlm/login.cgi
    с оригинальным body и минимальными браузерными headers.
    """
    login_url = make_url("/startwlm/login.cgi")

    # Подготовительные GET не критичны. Если Kyocera рвёт соединение, продолжаем.
    log("Подготовительный GET / ...")
    try:
        r0 = session.get(
            make_url("/"),
            headers={
                "User-Agent": session.headers["User-Agent"],
                "Accept-Encoding": "identity",
            },
            timeout=TIMEOUT,
        )
        log(f"GET / -> HTTP {r0.status_code}")
    except Exception as exc:
        log(f"GET / не выполнен, продолжаю: {exc}")

    login_body = build_raw_login_body()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": PRINTER_URL.rstrip("/"),
        "Referer": make_url("/startwlm/Start_Wlm.htm"),
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": session.headers["User-Agent"],
        "Accept-Encoding": "identity",
    }

    log(f"POST login URL: {login_url}")
    log("Отправляю логин как в captured_requests.json...")

    response = safe_post_with_wake(
        session,
        login_url,
        data=login_body,
        headers=headers,
        timeout=TIMEOUT,
        allow_redirects=False,
        stage="login",
        retries=3,
    )

    log(f"POST login -> HTTP {response.status_code}")
    log(f"Cookies после POST login: {session.cookies.get_dict()}")

    if response.status_code >= 400:
        save_response_debug(response, "kyocera_login_response_error.html")

        # Попробуем альтернативу: action из HTML иногда записан как ./startwlm/login.cgi.
        # Если сервер внезапно воспринимает относительный путь иначе, сразу покажем понятную диагностику.
        raise RuntimeError(
            f"POST {login_url} вернул HTTP {response.status_code}. "
            "По HAR этот URL должен быть рабочим. Проверьте, что скрипт запускается с того же IP/сети "
            "и что на принтере не исчерпан лимит сессий. Также попробуйте сначала нажать 'Выход из системы' "
            "в браузере Command Center RX."
        )

    save_response_debug(response, "kyocera_login_response_ok.html")

    # Успех в HAR возвращал страницу Start_Wlm/login.cgi с Admin и меню.
    if "Admin" not in response.text and "Адрес. книга" not in response.text and "Address Book" not in response.text:
        log("Внимание: ответ логина не содержит явных признаков Admin/Address Book.")

    verify_logged_in(session)


def verify_logged_in(session: requests.Session) -> None:
    log("Проверяю доступ к адресной книге...")

    r = safe_get_with_wake(
        session,
        make_url("/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1"),
        headers={
            "Referer": make_url("/startwlm/login.cgi"),
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": session.headers["User-Agent"],
            "Accept-Encoding": "identity",
        },
        timeout=TIMEOUT,
        stage="verify_addressbook",
        retries=3,
    )

    log(f"GET AddressBook -> HTTP {r.status_code}")

    if r.status_code >= 400:
        save_response_debug(r, "kyocera_addressbook_error.html")
        raise RuntimeError(f"Адресная книга не открылась: HTTP {r.status_code}")

    if "Адрес" not in r.text and "Address" not in r.text and "AddrBook" not in r.text:
        save_response_debug(r, "kyocera_addressbook_unexpected.html")
        raise RuntimeError("Адресная книга открылась, но страница не похожа на AddressBook.")

    log("Авторизация подтверждена.")



def parse_js_array_values(array_body: str) -> list[str]:
    """
    Примитивный парсер JavaScript Array(...), достаточный для Token = Array(...).
    Поддерживает строки в кавычках, числа и пустые значения.
    """
    values: list[str] = []
    current = []
    quote = ""
    escape = False

    for ch in array_body:
        if escape:
            current.append(ch)
            escape = False
            continue

        if ch == "\\":
            current.append(ch)
            escape = True
            continue

        if quote:
            if ch == quote:
                quote = ""
            else:
                current.append(ch)
            continue

        if ch in ("'", '"'):
            quote = ch
            continue

        if ch == ",":
            values.append("".join(current).strip())
            current = []
            continue

        current.append(ch)

    values.append("".join(current).strip())
    return values


def extract_token_arg6(addressbook_html: str) -> str:
    """
    Для старой ветки Command Center RX кнопка Add строит URL так:
    AddrBook_Addr_NewCntct_Prpty.htm?...&arg6="+Token[4]+"...
    На ECOSYS M3540idn Token[4] = 1, на части других моделей может быть 0.
    """
    match = re.search(r"Token\s*=\s*Array\s*\(([^)]*)\)", addressbook_html, flags=re.I | re.S)
    if not match:
        return ""

    values = parse_js_array_values(match.group(1))

    if len(values) > 4:
        value = values[4].strip().strip("'\"")
        if value in {"0", "1", "2", "3"}:
            return value

    return ""


def parse_max_count(text: str, default: int = 250) -> int:
    """
    Извлекает максимальный номер адресной книги, если прошивка его отдаёт.
    На M3540idn встречается h_getAbpMaxCount = "200".
    """
    for pattern in [
        r"h_getAbpMaxCount\s*=\s*[\"'](\d+)[\"']",
        r"_pp\.maxMemoryId\s*=\s*[\"'](\d+)[\"']",
        r"maxMemoryId\s*=\s*[\"'](\d+)[\"']",
    ]:
        value = regex_first(pattern, text)
        if value:
            try:
                parsed = int(value)
                if 1 <= parsed <= 999:
                    return parsed
            except ValueError:
                pass

    return default


def build_add_page_candidates(addressbook_html: str) -> list[str]:
    """
    Формирует список URL страницы добавления контакта для разных поколений Command Center RX.

    M3145dn:
      /basic/AddrBook_Addr_NewCntct_Prpty.htm?...arg6=0&arg50=0
      + отдельный model-файл.

    M3540idn:
      /basic/AddrBook_Addr_NewCntct_Prpty.htm?...arg6=1&arg50=0
      model-файла нет, форма/hidden находятся прямо в HTML.
    """
    candidates: list[str] = []

    token_arg6 = extract_token_arg6(addressbook_html)
    if token_arg6:
        candidates.append(
            f"/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6={token_arg6}&arg50=0"
        )
        candidates.append(
            f"/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6={token_arg6}&arg50=1"
        )

    # Известные варианты для двух поколений.
    candidates.extend([
        "/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0&arg50=0",
        "/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=1&arg50=0",
        "/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0",
        "/basic/AddrBook_Addr_NewCntct_Prpty.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=1",
        "/basic/AddrBook_Addr_NewCntct_Prpty.htm",
    ])

    result: list[str] = []
    for path in candidates:
        url = make_url(path)
        if url not in result:
            result.append(url)

    return result


def is_contact_add_page(html: str) -> bool:
    """
    Проверка, что открыта именно страница добавления контакта, а не список или ошибка.
    """
    lower = html.lower()

    strong_markers = [
        "addabppersonal",
        "addrbook_addr_newcntct_prpty",
        "arg06_sid",
        "arg07_name",
        "arg08_email",
        "arg09_smbaddress",
    ]

    return any(marker in lower for marker in strong_markers)


def extract_hidden_inputs(text: str) -> dict[str, str]:
    """
    Достаёт hidden inputs из HTML старого Command Center RX.
    Нужны для fallback и для определения hidden value.
    """
    hidden: dict[str, str] = {}

    for m in re.finditer(r"<input\b[^>]*>", text, flags=re.I | re.S):
        tag = m.group(0)
        typ = regex_first(r'type=["\']([^"\']*)["\']', tag).lower()
        name = regex_first(r'name=["\']([^"\']*)["\']', tag)
        value = regex_first(r'value=["\']([^"\']*)["\']', tag)

        if name and (typ == "hidden" or name == "hidden"):
            hidden[name] = value

    return hidden


def extract_contact_form_profile(html_text: str, page_url: str) -> ContactFormProfile:
    forms = re.findall(r"<form\b[^>]*>.*?</form>", html_text, flags=re.I | re.S)
    if not forms:
        return ContactFormProfile(make_url("/basic/set.cgi"), [])

    def score(form: str) -> int:
        lowered = form.casefold()
        return sum(
            weight
            for marker, weight in [
                ("addabppersonal", 8),
                ("arg07_name", 6),
                ("arg09_smbaddress", 6),
                ("adrscontact", 4),
                ("set.cgi", 2),
            ]
            if marker in lowered
        )

    selected = max(forms, key=score)
    form_tag = re.search(r"<form\b[^>]*>", selected, flags=re.I | re.S)
    action = ""
    if form_tag:
        action = regex_first(r'action\s*=\s*["\']([^"\']+)["\']', form_tag.group(0))
    action_url = absolute_action_url(page_url, action) if action else make_url("/basic/set.cgi")

    fields: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tag in re.findall(r"<input\b[^>]*>", selected, flags=re.I | re.S):
        name = regex_first(r'name\s*=\s*["\']([^"\']+)["\']', tag)
        if not name or name in seen:
            continue
        input_type = regex_first(r'type\s*=\s*["\']([^"\']+)["\']', tag).casefold()
        if input_type in {"submit", "reset", "button", "image", "file"}:
            continue
        explicitly_checked = bool(re.search(r"(?:^|\s)checked(?:\s|=|/|>)", tag, flags=re.I))
        if input_type in {"checkbox", "radio"} and not explicitly_checked:
            continue
        if input_type not in {"hidden", "checkbox", "radio"}:
            continue
        value = html.unescape(regex_first(r'value\s*=\s*["\']([^"\']*)["\']', tag))
        if "password" in name.casefold():
            continue
        if any(marker in value for marker in ("' +", '" +', "mes()[", "faxEncryptBoxNo", "ifaxAddress")):
            value = ""
        fields.append((name, value))
        seen.add(name)

    return ContactFormProfile(action_url, fields)



def parse_used_numbers(text: str) -> set[int]:
    """
    Извлекает занятые номера адресной книги без ложных срабатываний.

    Важно:
    Старый вариант искал любые три цифры в HTML. На M3540idn это давало мусор
    из CSS/JavaScript/размеров и приводило к неверному выводу, что 001 свободен.

    Теперь порядок такой:
    1. Основной способ для старого WLM-интерфейса M3540idn:
       AddrNumber[index] = "1" ... "9".
    2. Способ для нового/Knockout-интерфейса M3145dn:
       dataRows/ссылки/ячейки с номером 001, 002, 016.
    3. Осторожный fallback по HTML-ячейкам/ссылкам, а не по любым цифрам.
    """
    used: set[int] = set()

    # M3540idn: в HTML есть строки вида:
    # AddrNumber[index] = "1";
    # AddrNumber[index] = "2";
    for raw in re.findall(r"AddrNumber\s*\[[^\]]+\]\s*=\s*[\"'](\d{1,3})[\"']", text, flags=re.I):
        num = int(raw)
        if 1 <= num <= 250:
            used.add(num)

    # Возможные варианты массива/данных в других прошивках.
    for pattern in [
        r"AddrNumber\s*=\s*Array\(([^)]*)\)",
        r"sCol1Data\s*=\s*Array\(([^)]*)\)",
    ]:
        for body in re.findall(pattern, text, flags=re.I | re.S):
            for raw in re.findall(r"[\"'](\d{1,3})[\"']", body):
                num = int(raw)
                if 1 <= num <= 250:
                    used.add(num)

    # Рендеренный HTML / Knockout-страницы: номер обычно в ссылке/ячейке как 001.
    # Не ищем любые три цифры в документе, чтобы не ловить width=100, mes[107] и т.п.
    html_number_patterns = [
        r">\s*(\d{1,3})\s*</a>",
        r">\s*(\d{1,3})\s*</td>",
        r"value=[\"'](\d{1,3})[\"'][^>]*(?:name|id)=[\"'][^\"']*(?:box|addr|number|sid)",
        r"(?:name|id)=[\"'][^\"']*(?:box|addr|number|sid)[^\"']*[\"'][^>]*value=[\"'](\d{1,3})[\"']",
    ]

    for pattern in html_number_patterns:
        for raw in re.findall(pattern, text, flags=re.I | re.S):
            num = int(raw)
            if 1 <= num <= 250:
                used.add(num)

    return used


def first_free_from_used(used: set[int], max_count: int = 250) -> str:
    for number in range(1, max_count + 1):
        if number not in used:
            return f"{number:03d}"

    raise RuntimeError(f"Не найден свободный номер 001-{max_count:03d}.")


def get_first_free_number_from_addressbook(session: requests.Session) -> str:
    """
    Универсальный fallback для старых/других прошивок.
    1. Пытаемся найти emptyMemoryId в model/list.
    2. Иначе собираем занятые номера из HTML списка и берём первый свободный.
    """
    log("Пытаюсь определить свободный номер через список адресной книги...")

    used: set[int] = set()
    max_count = 250

    candidates = [
        "/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=NaN&arg6=0&arg7=0&arg8=&arg9=0",
        "/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=1&arg5=NaN&arg6=0&arg7=0&arg8=&arg9=0",
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1",
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1&arg5=0&arg6=0&arg7=0&arg9=0",
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=NaN&arg6=0&arg7=0&arg9=0",
    ]

    referer = make_url("/startwlm/login.cgi")

    for path in candidates:
        url = make_url(path)
        try:
            r = get_with_debug(session, url, referer, "addressbook_number_probe")
        except Exception as exc:
            log(f"Не удалось получить {path}: {exc}")
            continue

        if r.status_code != 200:
            continue

        max_count = max(max_count, parse_max_count(r.text, default=max_count))

        try:
            free = parse_empty_memory_id(r.text)
            log(f"Свободный номер найден через emptyMemoryId списка: {free}")
            return free
        except Exception:
            pass

        used.update(parse_used_numbers(r.text))

    if used:
        free = first_free_from_used(used, max_count=max_count)
        log(f"Свободный номер вычислен по списку: {free}. Занятые: {sorted(used)[:30]}...")
        return free

    raise RuntimeError(
        "Не удалось определить свободный номер автоматически. "
        "Укажите CONTACT_NUMBER вручную, например CONTACT_NUMBER = '016'."
    )


def find_model_text_from_add_page(
    session: requests.Session,
    add_page_url: str,
    add_page_html: str,
) -> str:
    """
    Универсально ищет model-файл формы добавления контакта.

    На ECOSYS M3145dn работал прямой путь:
    /js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?...

    На ECOSYS M3540idn этот прямой путь может давать 404, поэтому:
    1. берём script src из HTML страницы добавления;
    2. пробуем несколько вариантов query;
    3. если модели нет — возвращаем пустую строку, а дальше используем fallback.
    """
    model_urls: list[str] = []

    # 1. Самый надёжный способ: взять script src прямо из HTML add-page.
    for url in extract_script_urls(add_page_html, add_page_url, "model"):
        if "addrbook" in url.lower() and url not in model_urls:
            model_urls.append(url)

    # 2. Дополнительные кандидаты для разных прошивок.
    extra_paths = [
        "/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0&arg50=0",
        "/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=1&arg50=0",
        "/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0",
        "/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=1",
        "/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm",
        "/wlmpor/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0&arg50=0",
        "/wlmeng/js/jssrc/model/basic/AddrBook_Addr_NewCntct_Prpty.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=0&arg50=0",
    ]

    for path in extra_paths:
        url = make_url(path)
        if url not in model_urls:
            model_urls.append(url)

    referer = add_page_url

    for index, url in enumerate(model_urls, start=1):
        try:
            r = get_with_debug(session, url, referer, f"add_model_candidate_{index}")
        except Exception as exc:
            log(f"Кандидат model не открылся: {url}; {exc}")
            continue

        if r.status_code == 200:
            text = r.text or ""
            # Даже если emptyMemoryId нет, hidden/model может быть полезен.
            if "emptyMemoryId" in text or "hiddenvalue" in text or "_pp." in text:
                log(f"Model формы найден: {url}")
                return text

    log("Model формы добавления контакта не найден. Будет использован fallback без model.")
    return ""


def get_new_contact_model(session: requests.Session) -> tuple[str, str, str]:
    """
    Открывает страницу добавления контакта адаптивно.

    Важное различие:
    - ECOSYS M3145dn: add-page + отдельный model-файл.
    - ECOSYS M3540idn: add-page содержит форму/hidden прямо в HTML, model-файла может не быть.
    """
    referer = make_url("/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1")

    log("Открываю список адресной книги для определения типа прошивки...")
    r_list = session.get(
        referer,
        headers={
            "Referer": make_url("/startwlm/login.cgi"),
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": session.headers["User-Agent"],
            "Accept-Encoding": "identity",
        },
        timeout=TIMEOUT,
    )
    log(f"GET addressbook list for discovery -> HTTP {r_list.status_code}")

    addressbook_html = r_list.text if r_list.status_code == 200 else ""
    if addressbook_html:
        save_text_debug(addressbook_html, "kyocera_addressbook_discovery.html")

    add_page_candidates = build_add_page_candidates(addressbook_html)

    add_page_url = ""
    add_page_text = ""

    for url in add_page_candidates:
        log(f"Открываю страницу добавления контакта: {url}")

        r_page = session.get(
            url,
            headers={
                "Referer": referer,
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": session.headers["User-Agent"],
                "Accept-Encoding": "identity",
            },
            timeout=TIMEOUT,
        )

        log(f"GET add page -> HTTP {r_page.status_code}")

        if r_page.status_code == 200 and is_contact_add_page(r_page.text):
            add_page_url = url
            add_page_text = r_page.text
            save_text_debug(add_page_text, "kyocera_add_page_ok.html")
            break

        if r_page.status_code >= 400:
            save_response_debug(r_page, "kyocera_add_page_error.html")

    if not add_page_url:
        raise RuntimeError("Не удалось открыть страницу добавления контакта ни по одному известному URL.")

    model_text = find_model_text_from_add_page(session, add_page_url, add_page_text)
    combined_text = f"{addressbook_html}\n{add_page_text}\n{model_text}"

    if CONTACT_NUMBER.strip():
        first_free_id = CONTACT_NUMBER.strip()
        log(f"Использую номер из CONTACT_NUMBER: {first_free_id}")
    else:
        try:
            first_free_id = parse_empty_memory_id(combined_text)
            log(f"Первый свободный номер найден через emptyMemoryId: {first_free_id}")
        except Exception:
            first_free_id = get_first_free_number_from_addressbook(session)

    hidden_value = parse_hidden_value(combined_text)

    log(f"Номер для контакта: {first_free_id}")
    log(f"hidden value: {hidden_value}")
    log(f"add page URL: {add_page_url}")

    return first_free_id, hidden_value, add_page_url


def load_contact_form_profile(
    session: requests.Session,
    add_page_url: str,
) -> ContactFormProfile:
    response = safe_get_with_wake(
        session,
        add_page_url,
        headers={
            "Referer": make_url("/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1"),
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": session.headers["User-Agent"],
            "Accept-Encoding": "identity",
        },
        timeout=TIMEOUT,
        stage="load_contact_form",
        retries=2,
    )
    if response.status_code >= 400 or not is_contact_add_page(response.text):
        raise RuntimeError(
            f"Не удалось повторно прочитать форму контакта: HTTP {response.status_code}."
        )
    profile = extract_contact_form_profile(response.text, add_page_url)
    log(f"POST action формы: {profile.action_url}")
    log(f"Скрытых/служебных полей формы: {len(profile.default_fields)}")
    return profile



class KyoceraBasicErr(RuntimeError):
    """
    Kyocera вернула Contact_BasicErr.
    Обычно это не ошибка HTTP, а отказ самой формы:
    - занят номер адресной книги;
    - уже есть такой контакт;
    - не приняты отдельные поля формы;
    - некорректный hidden/token для конкретной страницы.
    """
    def __init__(self, stage: str, response: requests.Response):
        self.stage = stage
        self.response = response
        self.message_text = extract_basic_error_text(response.text)
        super().__init__(f"{stage}: Kyocera вернула Contact_BasicErr. {self.message_text}".strip())


def strip_html(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_basic_error_text(html: str) -> str:
    """
    Пытается вытащить человекочитаемый текст из Contact_BasicErr.
    На части Kyocera ошибка не содержит нормального текста, тогда вернётся пусто.
    """
    plain = strip_html(html or "")

    # Убираем слишком длинный мусор JS/меню.
    interesting = []
    for marker in [
        "Ошибка",
        "ошибка",
        "Error",
        "error",
        "Невер",
        "недопуст",
        "существ",
        "занят",
        "already",
        "invalid",
        "duplicate",
    ]:
        pos = plain.find(marker)
        if pos >= 0:
            interesting.append(plain[max(0, pos - 80):pos + 220])

    if interesting:
        return " | ".join(dict.fromkeys(interesting))[:600]

    return ""


def save_add_payload_debug(payload: list[tuple[str, str]], filename: str = "kyocera_last_add_payload.txt") -> None:
    """
    Сохраняет последний payload добавления контакта.
    Пароли маскируются.
    """
    try:
        lines = []
        for key, value in payload:
            safe_value = value
            if "password" in key.lower():
                safe_value = "********"
            lines.append(f"{key}={safe_value}")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        log(f"Payload сохранён: {filename}")
    except Exception as exc:
        log(f"Не удалось сохранить payload: {exc}")


def get_used_numbers_snapshot(session: requests.Session) -> tuple[set[int], int]:
    """
    Получает снимок занятых номеров из адресной книги.
    Используется для авто-повтора, если Kyocera вернула BasicErr.
    """
    used: set[int] = set()
    max_count = 250

    candidates = [
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1",
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1&arg5=0&arg6=0&arg7=0&arg9=0",
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=NaN&arg6=0&arg7=0&arg9=0",
        "/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=1&arg5=NaN&arg6=0&arg7=0&arg8=&arg9=0",
        "/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=0&arg5=NaN&arg6=0&arg7=0&arg8=&arg9=0",
    ]

    referer = make_url("/startwlm/login.cgi")

    for path in candidates:
        try:
            r = session.get(
                make_url(path),
                headers={
                    "Referer": referer,
                    "Upgrade-Insecure-Requests": "1",
                    "User-Agent": session.headers["User-Agent"],
                    "Accept-Encoding": "identity",
                },
                timeout=TIMEOUT,
            )
        except Exception:
            continue

        if r.status_code != 200:
            continue

        max_count = max(max_count, parse_max_count(r.text, default=max_count))
        used.update(parse_used_numbers(r.text))

    return used, max_count


def next_free_numbers(used: set[int], max_count: int = 250, limit: int = 20) -> list[str]:
    result: list[str] = []

    for number in range(1, max_count + 1):
        if number not in used:
            result.append(f"{number:03d}")
            if len(result) >= limit:
                break

    return result


def build_add_contact_payload(
    contact: KyoceraContact,
    hidden_value: str,
    form_profile: ContactFormProfile | None = None,
) -> list[tuple[str, str]]:
    required_fields = [
        ("okhtmfile", "/basic/Contact_BasicRslt.htm"),
        ("failhtmfile", "/basic/Contact_BasicErr.htm"),
        ("func", "addAbpPersonal"),
        ("arg01_PageNum", "1"),
        ("arg02_Sort", "0"),
        ("arg03_Search", ""),
        ("arg04_pageType", "0"),
        ("arg05_MemoryID", ""),
        ("arg12_SMBPassword", contact.smb_password),
        ("arg50", "0"),
        ("arg25_furi", ""),
        ("arg51", "0"),
        ("hidden", hidden_value),
        ("arg06_sID", contact.number),
        ("arg07_Name", contact.name),
        ("arg08_Email", contact.email),
        ("arg09_SMBAddress", contact.smb_host),
        ("arg38", contact.smb_port),
        ("arg10_SMBPathName", contact.smb_path),
        ("arg11_SMBLoginName", contact.smb_username),
        ("SMBPassword", contact.smb_password),
        ("arg13_FTPAddress", ""),
        ("arg39", "21"),
        ("arg14_FTPPathName", ""),
        ("arg15_FTPLoginName", ""),
        ("FTPPassword", ""),

        # Поля M3540idn / ECOSYS M3540idn.
        ("arg17_FAXNumber", ""),
        ("arg20_FCodeSubAddr", ""),
        ("arg18_BaudRate", "0"),
        ("arg19_ECM", "1"),
        ("arg22_EncryptionKey", "0"),

        ("submit001", "Передать"),
    ]
    if not form_profile:
        return required_fields

    values: dict[str, str] = {}
    order: list[str] = []
    for name, value in form_profile.default_fields:
        if name not in values:
            order.append(name)
        values[name] = value
    for name, value in required_fields:
        if name not in values:
            order.append(name)
        values[name] = value
    return [(name, values[name]) for name in order]


def post_add_contact_once(
    session: requests.Session,
    contact: KyoceraContact,
    hidden_value: str,
    add_page_url: str,
    form_profile: ContactFormProfile | None = None,
) -> requests.Response:
    payload = build_add_contact_payload(contact, hidden_value, form_profile)
    save_add_payload_debug(payload)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": PRINTER_URL.rstrip("/"),
        "Referer": add_page_url,
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": session.headers["User-Agent"],
        "Accept-Encoding": "identity",
        "Connection": "close",
    }

    log(f"Отправляю контакт с номером {contact.number}...")
    r = session.post(
        form_profile.action_url if form_profile else make_url("/basic/set.cgi"),
        data=payload,
        headers=headers,
        timeout=ADD_CONTACT_TIMEOUT_SECONDS,
        allow_redirects=False,
    )

    if is_energy_saver_response(r.text):
        log("add_contact: принтер вернул DeepSleep/EnergySaver вместо результата POST.")
        wait_printer_ready(session, stage="add_contact")
        raise RuntimeError(
            "Принтер ушёл в энергосбережение во время сохранения контакта. "
            "POST не повторён, чтобы не создать дубль. Попробуйте ещё раз после пробуждения устройства."
        )

    log(f"POST add contact -> HTTP {r.status_code}")
    return r


def contact_exists(
    session: requests.Session,
    contact: KyoceraContact,
    *,
    retries: int = 1,
    quiet: bool = False,
) -> bool:
    if quiet:
        log("Аккуратно проверяю, появилась ли запись в адресной книге...")
    else:
        log("Проверяю список адресной книги...")

    list_paths = [
        (
            f"/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1"
            f"&arg5=NaN&arg6=0&arg7=0&arg9={contact.number}"
        ),
        "/basic/AddrBook_Addr.htm?arg1=1&arg2=0&arg3=&arg4=1",
        (
            f"/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=1"
            f"&arg5=NaN&arg6=0&arg7=0&arg8=&arg9={contact.number}"
        ),
        "/js/jssrc/model/basic/AddrBook_Addr.model.htm?arg1=1&arg2=0&arg3=&arg4=1&arg5=NaN&arg6=0&arg7=0&arg8=&arg9=0",
    ]
    combined = ""

    for index, path in enumerate(list_paths, start=1):
        url = make_url(path)
        try:
            response = safe_get_with_wake(
                session,
                url,
                headers={
                    "Referer": make_url("/startwlm/login.cgi"),
                    "Upgrade-Insecure-Requests": "1",
                    "User-Agent": session.headers["User-Agent"],
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
                timeout=TIMEOUT,
                stage=("проверка адресной книги" if quiet else f"verify_contact_{index}"),
                retries=retries,
                log_attempt_errors=not quiet,
            )
        except Exception as exc:
            if not quiet:
                log(f"Проверка адресной книги #{index} не выполнена: {exc}")
            continue

        if not quiet:
            log(f"GET addressbook verify #{index} -> HTTP {response.status_code}")
        if response.status_code == 200:
            combined += "\n" + (response.text or "")

    lowered = combined.casefold()
    probes = [
        contact.email.casefold(),
        contact.name.casefold(),
    ]
    if any(probe and probe in lowered for probe in probes):
        log("Контакт найден в списке/model.")
        return True

    if combined:
        log("Контакт пока не виден в HTML/model адресной книги.")
    else:
        log("Принтер сейчас не отдал список адресной книги для проверки.")
    return False


def verify_contact_after_indeterminate_post(
    session: requests.Session,
    contact: KyoceraContact,
    error: Exception,
) -> bool:
    log(
        "Принтер не вернул понятный ответ на сохранение контакта. "
        "POST не повторяю, чтобы не создать дубль; проверяю результат через адресную книгу."
    )
    for attempt in range(1, 4):
        if attempt > 1:
            time.sleep(POST_COMMIT_VERIFY_DELAY_SECONDS)
        try:
            wait_printer_ready(session, stage=f"verify_after_add_attempt_{attempt}")
        except Exception as exc:
            log(f"Принтер ещё не готов после POST, попытка проверки #{attempt}: {exc}")
            continue
        if contact_exists(session, contact, retries=1, quiet=True):
            log("Контакт найден после неоднозначного ответа POST. Считаю операцию успешной.")
            return True
    log(
        "Не удалось подтвердить контакт через адресную книгу. "
        "Повторная отправка не выполнялась, чтобы не создать дубль."
    )
    return False


def ensure_success_response(response: requests.Response, stage: str) -> None:
    if response.status_code >= 400:
        save_response_debug(response, f"kyocera_{stage}_error.html")
        raise RuntimeError(f"{stage}: HTTP {response.status_code}")

    lower = response.text.lower()

    if "contact_basicerr" in lower or "basicerr" in lower:
        save_response_debug(response, f"kyocera_{stage}_basicerr.html")
        raise KyoceraBasicErr(stage, response)

    if "arg02_password" in lower:
        save_response_debug(response, f"kyocera_{stage}_login_page.html")
        raise RuntimeError(f"{stage}: Kyocera вернула страницу логина.")


def add_contact(
    session: requests.Session,
    contact: KyoceraContact,
    hidden_value: str,
    add_page_url: str,
    form_profile: ContactFormProfile | None = None,
) -> None:
    """
    Отправляет контакт в Kyocera.

    Новое поведение v8:
    если Kyocera вернула Contact_BasicErr, скрипт не останавливается сразу,
    а пробует следующие свободные номера адресной книги. Это полезно для
    одинаковых моделей, где одна машина уже заняла часть номеров, а HTML-список
    отдаёт номера не полностью или нестабильно.
    """
    manual_number = bool(CONTACT_NUMBER.strip())

    attempt_numbers = [contact.number]

    if not manual_number:
        try:
            used, max_count = get_used_numbers_snapshot(session)
            # На случай если текущий номер реально занят, добавляем его в used после первой ошибки.
            for candidate in next_free_numbers(used, max_count=max_count, limit=30):
                if candidate not in attempt_numbers:
                    attempt_numbers.append(candidate)
        except Exception as exc:
            log(f"Не удалось получить снимок занятых номеров для retry: {exc}")

    last_basic_error: KyoceraBasicErr | None = None

    for attempt_index, number in enumerate(attempt_numbers, start=1):
        contact.number = number

        if attempt_index > 1:
            log(f"Повторная попытка #{attempt_index}: пробую номер {number}")

        try:
            r = post_add_contact_once(
                session,
                contact,
                hidden_value,
                add_page_url,
                form_profile,
            )
            ensure_success_response(r, "add_contact")
            save_response_debug(r, "kyocera_add_contact_response.html")
            log("Принтер принял запись адресной книги.")
            return
        except KyoceraBasicErr as exc:
            last_basic_error = exc
            log(f"Kyocera вернула BasicErr для номера {number}.")
            if exc.message_text:
                log(f"Текст ошибки Kyocera: {exc.message_text}")

            # При ручном номере не перебираем дальше, чтобы не создать запись не там, где ожидает админ.
            if manual_number:
                raise

            # Если BasicErr связан не с номером, следующие попытки тоже могут падать.
            # Но для разных адресных книг самая частая причина — занятый номер.
            continue
        except requests.exceptions.RequestException as exc:
            if verify_contact_after_indeterminate_post(session, contact, exc):
                return
            raise RuntimeError(
                "Kyocera оборвала соединение или не ответила на POST добавления контакта. "
                "Повторный POST не выполнен, чтобы не создать дубль. "
                "После ожидания контакт в адресной книге не найден. "
                "Проверьте состояние принтера и попробуйте повторить операцию."
            ) from exc

    if last_basic_error:
        raise RuntimeError(
            "Kyocera вернула Contact_BasicErr на всех попытках добавления. "
            "С высокой вероятностью причина не в номере, а в данных контакта: "
            "такой контакт/email уже есть, не принимается SMB-путь/пользователь, "
            "или конкретная прошивка требует другой набор POST-полей. "
            "Проверьте kyocera_add_contact_basicerr.html и kyocera_last_add_payload.txt."
        ) from last_basic_error

    raise RuntimeError("Не выполнена ни одна попытка добавления контакта.")


def verify_contact(session: requests.Session, contact: KyoceraContact) -> bool:
    if contact_exists(session, contact, retries=1, quiet=True):
        return True
    log(
        "POST добавления контакта завершился без HTTP-ошибки, "
        "но контакт не найден текстовым поиском при проверке. "
        "Не считаю это фатальной ошибкой: на части Kyocera список адресной книги "
        "обновляется через JS/кэш и не всегда сразу содержит новую запись."
    )
    return False



def parse_args() -> argparse.Namespace:
    """
    Аргументы командной строки.

    Все параметры имеют значения по умолчанию из блока НАСТРОЙКИ,
    поэтому скрипт можно запускать как без аргументов, так и из n8n/SSH
    с передачей нужных данных сотрудника.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Добавление контакта в адресную книгу Kyocera Command Center RX "
            "для ECOSYS M3145dn / M3540idn / MA4500x и похожих моделей."
        )
    )

    parser.add_argument(
        "--printer",
        default=PRINTER_URL,
        help=f"URL принтера, например http://10.14.32.40. По умолчанию: {PRINTER_URL}",
    )

    parser.add_argument(
        "--admin-login",
        default=KYOCERA_ADMIN_LOGIN,
        help=f"Логин администратора Kyocera. По умолчанию: {KYOCERA_ADMIN_LOGIN}",
    )

    parser.add_argument(
        "--admin-password",
        default=KYOCERA_ADMIN_PASSWORD,
        help="Пароль администратора Kyocera.",
    )

    parser.add_argument(
        "--full-name",
        default=CONTACT_FULL_NAME,
        help=f"Полное ФИО сотрудника. По умолчанию: {CONTACT_FULL_NAME}",
    )

    parser.add_argument(
        "--login",
        default=CONTACT_LOGIN,
        help=f"Логин сотрудника, например a.nikitin. По умолчанию: {CONTACT_LOGIN}",
    )

    parser.add_argument(
        "--email",
        default=CONTACT_EMAIL,
        help=f"Email сотрудника. По умолчанию: {CONTACT_EMAIL}",
    )

    parser.add_argument(
        "--number",
        default=CONTACT_NUMBER,
        help=(
            "Номер в адресной книге, например 010. "
            "Если оставить пустым, скрипт попробует определить первый свободный номер автоматически."
        ),
    )

    parser.add_argument(
        "--smb-host",
        default=SMB_HOST,
        help=f"SMB host. По умолчанию: {SMB_HOST}",
    )

    parser.add_argument(
        "--smb-port",
        default=SMB_PORT,
        help=f"SMB port. По умолчанию: {SMB_PORT}",
    )

    parser.add_argument(
        "--smb-username",
        default=SMB_USERNAME,
        help=f"SMB пользователь. По умолчанию: {SMB_USERNAME}",
    )

    parser.add_argument(
        "--smb-password",
        default=SMB_PASSWORD,
        help="SMB пароль.",
    )

    parser.add_argument(
        "--smb-base-path",
        default=SMB_BASE_PATH,
        help=f"SMB путь к корню пользовательских папок без host, например fs\\USERFOLDER. По умолчанию: {SMB_BASE_PATH}",
    )

    parser.add_argument(
        "--smb-scan-subfolder",
        default=SMB_SCAN_SUBFOLDER,
        help=f"Имя scan-папки внутри папки пользователя. По умолчанию: {SMB_SCAN_SUBFOLDER}",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Проверить подключение, авторизацию, адресную книгу и форму нового контакта "
            "без отправки POST создания записи."
        ),
    )

    return parser.parse_args()

def main() -> int:
    global PRINTER_URL
    global KYOCERA_ADMIN_LOGIN
    global KYOCERA_ADMIN_PASSWORD
    global SMB_HOST
    global SMB_PORT
    global SMB_USERNAME
    global SMB_PASSWORD
    global SMB_BASE_PATH
    global SMB_SCAN_SUBFOLDER
    global CONTACT_FULL_NAME
    global CONTACT_LOGIN
    global CONTACT_EMAIL
    global CONTACT_NUMBER

    args = parse_args()

    PRINTER_URL = normalize_printer_url(args.printer)
    KYOCERA_ADMIN_LOGIN = args.admin_login
    KYOCERA_ADMIN_PASSWORD = args.admin_password

    CONTACT_FULL_NAME = args.full_name
    CONTACT_LOGIN = args.login
    CONTACT_EMAIL = args.email
    CONTACT_NUMBER = args.number

    SMB_HOST = args.smb_host
    SMB_PORT = args.smb_port
    SMB_USERNAME = args.smb_username
    SMB_PASSWORD = args.smb_password
    SMB_BASE_PATH = args.smb_base_path.strip("\\/")
    SMB_SCAN_SUBFOLDER = args.smb_scan_subfolder.strip("\\/")

    session = create_session()

    preflight_printer_availability()
    discover_printer_base_url(session)
    wait_printer_ready(session, stage="startup")
    login(session)

    first_free_id, hidden_value, add_page_url = get_new_contact_model(session)
    form_profile = load_contact_form_profile(session, add_page_url)

    if args.check_only:
        log(
            "ПРОВЕРКА УСПЕШНА: авторизация, адресная книга, свободный номер "
            "и форма добавления доступны. Контакт не создавался."
        )
        return 0

    contact_number = CONTACT_NUMBER.strip() or first_free_id

    contact = KyoceraContact(
        number=contact_number,
        name=make_short_name(CONTACT_FULL_NAME),
        email=CONTACT_EMAIL,
        smb_host=SMB_HOST,
        smb_port=SMB_PORT,
        smb_path=build_smb_path(CONTACT_LOGIN),
        smb_username=SMB_USERNAME,
        smb_password=SMB_PASSWORD,
    )

    log("Контакт для добавления:")
    log(f"Принтер: {PRINTER_URL}")
    log(f"Номер: {contact.number}")
    log(f"Имя: {contact.name}")
    log(f"Email: {contact.email}")
    log(f"SMB host: {contact.smb_host}")
    log(f"SMB port: {contact.smb_port}")
    log(f"SMB path: {contact.smb_path}")
    log(f"SMB user: {contact.smb_username}")

    add_contact(session, contact, hidden_value, add_page_url, form_profile)
    log(
        "Проверку списка после успешного POST не запускаю: "
        "Kyocera уже приняла запись, а адресная книга на части моделей обновляется с задержкой."
    )

    log("ГОТОВО.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
