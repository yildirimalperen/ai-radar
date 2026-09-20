"""İsteğe bağlı LLM katmanı: seçilen maddelere 'neden önemli' satırı ekler.

Bilinçli olarak dar tutuldu. Sıralamayı heuristik skorlayıcı yapıyor -- o
deterministik, test edilebilir ve bedava. LLM yalnız son listeye (≤12 madde)
tek cümlelik bağlam yazıyor. Böylece:
  * anahtar yoksa boru hattı aynen çalışır, yalnız bu cümleler eksik olur,
  * maliyet koşu başına birkaç kuruşta kalır,
  * sıralamadaki bir hatayı LLM'e değil skor kırılımına bakarak bulabiliriz.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .models import Item

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 60

PROMPT = """Aşağıda bir AI/üretken-medya radarının bugünkü maddeleri var. Okuyucu,
oyun ve görsel üretimi üzerine çalışan bir mühendislik yöneticisi; ilgi alanları
görsel/video üretimi, oyun üretimi, 3D ve rigging boru hattı, yeni modeller ve
öncü şirketler.

Her madde için TEK cümlelik Türkçe bir "neden önemli" notu yaz. Kurallar:
- Başlığı tekrar etme; başlıktan anlaşılmayan bağlamı ver.
- Somut ol. Abartma, pazarlama dili kullanma.
- Madde okuyucunun işine dokunmuyorsa bunu dürüstçe yaz.
- En fazla 25 kelime.

Yalnızca şu biçimde JSON dön: {"notes": {"<key>": "<cümle>", ...}}

Maddeler:
%s
"""


def annotate(items: list[Item]) -> tuple[list[Item], str]:
    """Maddelere 'why' notu ekler. Döner: (maddeler, durum_mesajı)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return items, "atlandı (ANTHROPIC_API_KEY yok)"
    if not items:
        return items, "atlandı (madde yok)"

    listing = "\n".join(
        f'- key={i.key} | {i.title} | kaynak={i.source} | eksen={",".join(i.axes)}'
        f'{" | " + i.summary[:180] if i.summary else ""}'
        for i in items
    )
    payload = {
        "model": MODEL,
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": PROMPT % listing}],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return items, f"başarısız (HTTP {exc.code}: {exc.read()[:120].decode('utf-8', 'replace')})"
    except Exception as exc:  # noqa: BLE001 - LLM katmanı koşuyu düşürmemeli
        return items, f"başarısız ({type(exc).__name__}: {exc})"

    text = "".join(block.get("text", "") for block in body.get("content", []))
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return items, "başarısız (yanıtta JSON yok)"

    try:
        notes = json.loads(text[start : end + 1]).get("notes", {})
    except json.JSONDecodeError:
        return items, "başarısız (JSON ayrıştırılamadı)"

    hits = 0
    for item in items:
        note = notes.get(item.key)
        if note:
            item.why = str(note).strip()
            hits += 1
    usage = body.get("usage", {})
    return items, (
        f"tamam ({hits}/{len(items)} not, "
        f"{usage.get('input_tokens', '?')}→{usage.get('output_tokens', '?')} token)"
    )
