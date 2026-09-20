"""Aday kaynakları tek tek yoklar: canlı mı, kaç madde veriyor, son giriş ne zaman.
sources.yaml'ı varsayımla değil ölçümle yazmak için."""
import concurrent.futures as cf
import sys
import urllib.request

UA = "ai-radar/0.1 (+https://github.com/yildirimalperen)"

CANDIDATES = [
    # laboratuvar / şirket duyuruları
    ("openai",            "https://openai.com/news/rss.xml"),
    ("anthropic",         "https://www.anthropic.com/news/rss.xml"),
    ("deepmind",          "https://deepmind.google/blog/rss.xml"),
    ("meta-ai",           "https://ai.meta.com/blog/rss/"),
    ("huggingface-blog",  "https://huggingface.co/blog/feed.xml"),
    ("mistral",           "https://mistral.ai/news/feed.xml"),
    ("stability",         "https://stability.ai/news?format=rss"),
    ("runway",            "https://runwayml.com/blog/rss.xml"),
    ("bfl",               "https://bfl.ai/blog/rss.xml"),
    ("fal-blog",          "https://blog.fal.ai/rss/"),
    ("fal-blog-alt",      "https://blog.fal.ai/index.xml"),
    ("replicate",         "https://replicate.com/blog/rss"),
    ("luma",              "https://lumalabs.ai/blog/rss.xml"),
    # github release / atom akışları
    ("comfyui-releases",  "https://github.com/comfyanonymous/ComfyUI/releases.atom"),
    ("blender-releases",  "https://github.com/blender/blender/tags.atom"),
    ("threejs-releases",  "https://github.com/mrdoob/three.js/releases.atom"),
    ("godot-releases",    "https://github.com/godotengine/godot/releases.atom"),
    # bültenler / analiz
    ("import-ai",         "https://importai.substack.com/feed"),
    ("the-batch",         "https://www.deeplearning.ai/the-batch/feed/"),
    ("last-week-in-ai",   "https://lastweekin.ai/feed"),
    ("ahead-of-ai",       "https://magazine.sebastianraschka.com/feed"),
    ("simonwillison",     "https://simonwillison.net/atom/everything/"),
    ("marktechpost",      "https://www.marktechpost.com/feed/"),
    ("techcrunch-ai",     "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("verge-ai",          "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("80lv",              "https://80.lv/feed/"),
    ("gamesindustry",     "https://www.gamesindustry.biz/feed"),
    # api tabanlı
    ("hn-algolia",        "https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points%3E80&hitsPerPage=5"),
    ("hf-papers-api",     "https://huggingface.co/api/daily_papers?limit=5"),
    ("arxiv-api",         "http://export.arxiv.org/api/query?search_query=cat:cs.CV&max_results=5&sortBy=submittedDate&sortOrder=descending"),
    ("reddit-sd",         "https://www.reddit.com/r/StableDiffusion/top.json?t=day&limit=5"),
    ("reddit-localllama", "https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=5"),
    ("reddit-aivideo",    "https://www.reddit.com/r/aivideo/top.json?t=day&limit=5"),
    ("reddit-gamedev",    "https://www.reddit.com/r/gamedev/top.json?t=day&limit=5"),
]


def probe(entry):
    name, url = entry
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(200_000)
            ctype = resp.headers.get("Content-Type", "?").split(";")[0]
            status = resp.status
    except Exception as exc:  # noqa: BLE001 - prob aracı, her hatayı raporlar
        return name, "FAIL", f"{type(exc).__name__}: {str(exc)[:70]}", url

    text = body.decode("utf-8", "replace")
    if "json" in ctype or text.lstrip().startswith(("{", "[")):
        kind, count = "json", text.count('"id"') or text.count('"title"')
    else:
        count = text.count("<item") + text.count("<entry")
        kind = "feed"
    verdict = "OK" if count else "EMPTY"
    return name, verdict, f"{status} {ctype} {kind} n~{count} {len(body)}B", url


with cf.ThreadPoolExecutor(max_workers=12) as pool:
    results = list(pool.map(probe, CANDIDATES))

ok = [r for r in results if r[1] == "OK"]
bad = [r for r in results if r[1] != "OK"]
for name, verdict, detail, _ in sorted(results, key=lambda r: (r[1] != "OK", r[0])):
    print(f"{verdict:5} {name:20} {detail}")
print(f"\nCANLI {len(ok)}/{len(results)} | ELENEN {len(bad)}", file=sys.stderr)
