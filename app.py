import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

OUTPUT_ROOT = Path(__file__).resolve().parent / "downloads"


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v) for v in value)
    text = str(value).replace("\xa0", " ").replace("\u200b", " ")
    return " ".join(text.split())


def normalize_url(url):
    if not isinstance(url, str):
        return ""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = "https://" + url
    return url


def first_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("url", "href", "value", "name", "displayName", "title", "text"):
            if key in value:
                nested = first_text(value[key])
                if nested:
                    return nested
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            nested = first_text(item)
            if nested:
                return nested
    return str(value)


def slugify(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:80] or "producto"


def file_stem(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:80] or "producto"


def clean_product_name(value):
    name = clean_text(value)
    if not name:
        return ""
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s*\[[^\]]*\]", "", name)
    name = re.sub(r"\s*[-|:]\s*([A-Z0-9]{2,})$", "", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" -:")
    return name


def make_id(value):
    return hashlib.md5(clean_text(value).lower().encode("utf-8")).hexdigest()[:12]


def fetch_html(url):
    final_url = normalize_url(url)
    response = requests.get(final_url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.text, response.url


def decode_nextjs_chunks(html):
    """Devuelve los textos serializados por Next.js (React Server Components)."""
    chunks = []
    pattern = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)
    for match in pattern.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        if len(payload) > 1 and isinstance(payload[1], str):
            chunks.append(payload[1])
    return chunks


def extract_next_data_payload(html):
    for pattern in (
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*\s+type=["\']application/json["\'][^>]*>(.*?)</script>',
        r'<script[^>]*type=["\']application/json["\'][^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    ):
        for match in re.finditer(pattern, html, flags=re.DOTALL | re.IGNORECASE):
            candidate = match.group(1).strip()
            if not candidate:
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def flatten_media_urls(value):
    items = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if current.startswith("http"):
                items.append(current)
        elif isinstance(current, dict):
            for key in ("url", "src", "image", "mediaUrl", "thumbnail", "thumbnailUrl", "publicPath"):
                if key in current and isinstance(current[key], str):
                    items.append(current[key])
            for nested in current.values():
                stack.append(nested)
        elif isinstance(current, list):
            stack.extend(current)
    return dedupe([normalize_url(item) for item in items if item])


def extract_nextjs_search_products(html, page_url):
    """Extrae productos listados en el JSON embebido de buscadores de e-commerce."""
    payload = extract_next_data_payload(html)
    if not payload:
        return []

    products = []
    seen = set()
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            items = node.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = clean_product_name(item.get("name") or item.get("displayName") or item.get("title"))
                    if not name:
                        continue

                    canonical = first_text(item.get("canonicalUrl") or item.get("url") or item.get("productUrl") or item.get("slug") or "")
                    if not canonical:
                        continue
                    canonical_lower = canonical.lower()
                    if not any(marker in canonical_lower for marker in ("/ip/", "/product", "/products/")):
                        continue

                    product_url = canonical if canonical.startswith("http") else urljoin(f"https://{urlparse(page_url).netloc}", canonical)
                    image_urls = flatten_media_urls(item.get("imageInfo") or item.get("images") or item.get("image") or {})
                    if not image_urls:
                        image_urls = flatten_media_urls(item.get("allImages") or item.get("media") or [])
                    price_value = item.get("price") if item.get("price") is not None else item.get("priceRange")
                    if isinstance(price_value, list) and price_value:
                        price_value = price_value[0]
                    if isinstance(price_value, dict):
                        price_value = price_value.get("value") or price_value.get("amount") or price_value.get("currency")

                    product = {
                        "name": name,
                        "price": clean_text(price_value),
                        "brand": clean_text(item.get("brand") or item.get("brandName") or item.get("vendor")),
                        "description": clean_text(item.get("shortDescription") or item.get("description") or "")[:500] or "Sin descripción disponible.",
                        "weight": clean_text(item.get("weight") or item.get("averageWeight") or ""),
                        "images": image_urls,
                        "product_id": str(item.get("id") or item.get("usItemId") or make_id(name + "|" + product_url)),
                        "url": product_url,
                        "source_url": page_url,
                    }
                    product_key = product["product_id"] or product["url"]
                    if product_key in seen:
                        continue
                    seen.add(product_key)
                    products.append(product)
            for value in node.values():
                stack.append(value)
        elif isinstance(node, list):
            for value in node:
                stack.append(value)
    return products


def extract_sodimac_products(html, page_url):
    """Extrae productos cuando el catálogo de Sodimac viene en __NEXT_DATA__."""
    if urlparse(page_url).hostname not in {"sodimac.cl", "www.sodimac.cl"}:
        return []

    payload = extract_next_data_payload(html)
    if not payload:
        return []

    results = []
    queue = [payload]
    while queue:
        node = queue.pop()
        if isinstance(node, dict):
            if isinstance(node.get("results"), list):
                results.extend(item for item in node["results"] if isinstance(item, dict))
            if isinstance(node.get("product"), dict):
                results.append(node["product"])
        if isinstance(node, (list, tuple)):
            for value in node:
                queue.append(value)
        elif isinstance(node, dict):
            for value in node.values():
                queue.append(value)

    if not results:
        return []

    products = []
    seen = set()
    for node in results:
        display_name = node.get("displayName") or node.get("name") or node.get("title") or node.get("productName")
        product_id = node.get("productId") or node.get("skuId") or node.get("id")
        if not display_name:
            continue

        media_urls = flatten_media_urls(node.get("mediaUrls") or node.get("media") or node.get("images"))
        if not product_id and not media_urls:
            continue

        name = clean_product_name(display_name)
        if not name:
            continue

        product_url = normalize_url(first_text(node.get("url") or node.get("productUrl") or node.get("canonicalUrl") or page_url))
        if not product_url and product_id:
            product_url = page_url

        price_candidates = node.get("prices")
        price_value = ""
        if isinstance(price_candidates, list):
            for candidate in price_candidates:
                if isinstance(candidate, dict):
                    raw_price = candidate.get("price")
                    if isinstance(raw_price, list):
                        raw_price = raw_price[0] if raw_price else ""
                    if raw_price:
                        price_value = clean_text(raw_price)
                        break
                elif isinstance(candidate, str):
                    price_value = clean_text(candidate)
                    break
        elif isinstance(price_candidates, dict):
            raw_price = price_candidates.get("price")
            if isinstance(raw_price, list):
                raw_price = raw_price[0] if raw_price else ""
            price_value = clean_text(raw_price)
        if not price_value:
            price_value = clean_text(node.get("price") or node.get("currentPrice"))

        brand = node.get("brand")
        if isinstance(brand, dict):
            brand_name = clean_text(brand.get("name") or brand.get("brandName") or brand.get("value"))
        elif isinstance(brand, (list, tuple)):
            brand_name = clean_text(brand[0] if brand else "")
        else:
            brand_name = clean_text(brand)
        if not brand_name:
            brand_name = clean_text(node.get("sellerName"))

        product_key = (product_id or product_url or name).lower()
        if product_key in seen:
            continue
        seen.add(product_key)
        products.append(
            {
                "name": name,
                "price": price_value,
                "brand": brand_name,
                "description": clean_text(node.get("description") or node.get("shortDescription") or "")[:500] or "Sin descripción disponible.",
                "weight": "",
                "images": media_urls,
                "product_id": str(product_id or make_id(name + "|" + product_url)),
                "url": product_url,
                "source_url": page_url,
            }
        )

    return products


def extract_solotodo_products(html, page_url):
    """Extrae el catálogo que SoloTodo incluye en el estado de su aplicación."""
    if urlparse(page_url).hostname not in {"solotodo.cl", "www.solotodo.cl"}:
        return []

    decoder = json.JSONDecoder()
    products = []
    seen = set()
    for chunk in decode_nextjs_chunks(html):
        cursor = 0
        marker = '"product":'
        while True:
            position = chunk.find(marker, cursor)
            if position < 0:
                break
            start = position + len(marker)
            try:
                raw_product, consumed = decoder.raw_decode(chunk[start:])
            except json.JSONDecodeError:
                cursor = start
                continue
            cursor = start + consumed

            image_url = clean_text(raw_product.get("picture_url"))
            product_id = raw_product.get("id")
            name = clean_text(raw_product.get("name"))
            if not product_id or not name or not image_url or product_id in seen:
                continue

            # El precio está en metadata, inmediatamente después del producto.
            price = ""
            price_match = re.match(
                r'.{0,300}?"offer_price":"([0-9.]+)"',
                chunk[cursor : cursor + 500],
                re.DOTALL,
            )
            if price_match:
                price = f"${int(float(price_match.group(1))):,}".replace(",", ".")

            brand = raw_product.get("brand") or {}
            specs = raw_product.get("specs") or {}
            slug = clean_text(raw_product.get("slug")) or slugify(name)
            weight = specs.get("weight")
            products.append(
                {
                    "name": name,
                    "price": price,
                    "brand": clean_text(brand.get("name") if isinstance(brand, dict) else brand),
                    "description": clean_text(
                        raw_product.get("meta_tag_description")
                        or raw_product.get("short_description")
                    )[:500] or "Sin descripción disponible.",
                    "weight": f"{weight} g" if weight is not None else "",
                    "images": [urljoin(page_url, image_url)],
                    "product_id": str(product_id),
                    "url": urljoin(page_url, f"/products/{product_id}-{slug}"),
                    "source_url": page_url,
                }
            )
            seen.add(product_id)
    return products


def dedupe(items):
    seen = set()
    out = []
    for item in items:
        value = clean_text(item)
        if not value:
            continue
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def extract_images_from_sources(soup, page_url):
    images = []

    for meta in soup.select('meta[property="og:image"], meta[name="twitter:image"]'):
        img_url = meta.get("content") or meta.get("content")
        if img_url:
            images.append(urljoin(page_url, img_url))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "{}")
        except Exception:
            continue
        candidates = []
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "image" in node and isinstance(node["image"], (list, str, dict)):
                    candidates.append(node["image"])
                for value in node.values():
                    stack.append(value)
            elif isinstance(node, list):
                for value in node:
                    stack.append(value)
        for candidate in candidates:
            if isinstance(candidate, str):
                images.append(urljoin(page_url, candidate))
            elif isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, str):
                        images.append(urljoin(page_url, item))
                    elif isinstance(item, dict):
                        url_value = item.get("url") or item.get("@id")
                        if url_value:
                            images.append(urljoin(page_url, url_value))

    for tag in soup.select('img[data-testid="product-card-image"], img[data-testid="product-card-image"]'):
        value = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if value:
            images.append(urljoin(page_url, value))

    for tag in soup.select("img[src], img[data-src], img[srcset], source[srcset]"):
        parent_product = tag.find_parent(attrs={"data-testid": "plp-product-card"})
        if not parent_product:
            continue
        for attr in ("src", "data-src", "data-lazy", "data-original", "srcset"):
            value = tag.get(attr)
            if value:
                if attr == "srcset":
                    value = value.split(",")[0].strip().split()[0]
                images.append(urljoin(page_url, value))
                break

    result = []
    for image_url in images:
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if any(ext in image_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"]):
            result.append(image_url)
    return dedupe(result)


def extract_schema_details(product_obj):
    if not isinstance(product_obj, dict):
        return {}, {}, {}

    def get_nested(mapping, *keys):
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
        return None

    name = get_nested(product_obj, "name")
    description = get_nested(product_obj, "description")
    brand = get_nested(product_obj, "brand")
    if isinstance(brand, dict):
        brand = brand.get("name") or brand.get("@id")
    price = get_nested(product_obj, "offers")
    if isinstance(price, dict):
        price = price.get("price")
    else:
        price = get_nested(product_obj, "price")
    weight = get_nested(product_obj, "weight")
    image = product_obj.get("image")
    return {
        "name": clean_text(name),
        "description": clean_text(description),
        "brand": clean_text(brand),
        "price": clean_text(price),
        "weight": clean_text(weight),
        "image": image,
    }, product_obj, product_obj


def extract_price_from_text(text):
    if not text:
        return ""
    match = re.search(r"(?:\$|USD|USD\s*)\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]+)?)", text)
    if match:
        return f"${match.group(1).replace('.', '').replace(',', '.') }"
    match = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]+)?)", text)
    if match:
        return match.group(1)
    return ""


def extract_weight_value(text):
    if not text:
        return ""
    match = re.search(r"(?i)(\d+(?:[.,]\d+)?)\s*(kg|kilogramos|kilo|g|gr|gramos|mg|lb|lbs)", text)
    if not match:
        return ""
    quantity = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit in {"kg", "kilogramos", "kilo"}:
        return f"{quantity:.2f} kg"
    if unit in {"g", "gr", "gramos"}:
        return f"{quantity:.0f} g"
    if unit in {"mg"}:
        return f"{quantity:.0f} mg"
    if unit in {"lb", "lbs"}:
        return f"{quantity:.2f} lb"
    return f"{quantity} {unit}"


def parse_product_page(page_url):
    html, final_url = fetch_html(page_url)
    soup = BeautifulSoup(html, "lxml")
    title = clean_text(soup.find("meta", property="og:title").get("content")) if soup.find("meta", property="og:title") else ""
    if not title:
        title = clean_text(soup.title.string) if soup.title else ""
    if not title:
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ")) if h1 else "Producto"

    product_data = {"name": clean_product_name(title), "price": "", "brand": "", "description": "", "weight": "", "images": []}

    for block in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(block.string or "{}")
        except Exception:
            continue
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                item_type = node.get("@type")
                if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
                    product_name = clean_product_name(node.get("name") or title)
                    product_data["name"] = product_name or product_data["name"]
                    product_data["description"] = clean_text(node.get("description") or product_data["description"])
                    brand = node.get("brand")
                    if isinstance(brand, dict):
                        product_data["brand"] = clean_text(brand.get("name"))
                    elif brand:
                        product_data["brand"] = clean_text(brand)
                    offers = node.get("offers")
                    if isinstance(offers, dict):
                        product_data["price"] = clean_text(offers.get("price"))
                    elif isinstance(offers, list) and offers:
                        first_offer = offers[0]
                        if isinstance(first_offer, dict):
                            product_data["price"] = clean_text(first_offer.get("price"))
                    product_data["weight"] = clean_text(node.get("weight"))
                    if node.get("image"):
                        value = node.get("image")
                        if isinstance(value, list):
                            product_data["images"].extend([urljoin(final_url, item) for item in value if isinstance(item, str)])
                        elif isinstance(value, str):
                            product_data["images"].append(urljoin(final_url, value))
                    continue
            if isinstance(node, list):
                for value in node:
                    stack.append(value)

    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta_desc and not product_data["description"]:
        product_data["description"] = clean_text(meta_desc.get("content"))

    if not product_data["brand"]:
        brand_meta = soup.find("meta", attrs={"name": "brand"})
        if brand_meta:
            product_data["brand"] = clean_text(brand_meta.get("content"))

    if not product_data["price"]:
        price_text = soup.get_text(" ")
        match = re.search(r"\$\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s*(?:USD|MXN)", price_text)
        if match:
            product_data["price"] = clean_text(match.group(0))

    if not product_data["weight"]:
        page_text = soup.get_text(" ")
        product_data["weight"] = extract_weight_value(page_text)

    product_data["images"] = dedupe(extract_images_from_sources(soup, final_url) + product_data["images"])
    product_data["name"] = clean_product_name(product_data["name"])
    product_data["product_id"] = make_id(product_data["name"] + "|" + final_url)
    product_data["url"] = final_url
    product_data["source_url"] = page_url
    if not product_data["images"]:
        product_data["images"] = [
            a.get("href") if a.get("href", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else ""
            for a in soup.select("a[href]")
            if a.get("href")
        ]
        product_data["images"] = dedupe([urljoin(final_url, item) for item in product_data["images"] if item])

    product_data["description"] = product_data["description"][:500] if product_data["description"] else "Sin descripción disponible."
    return product_data


def candidate_product_links(soup, page_url):
    urls = []
    for tag in soup.select("a[href]"):
        href = tag.get("href", "")
        if not href:
            continue
        candidate = urljoin(page_url, href)
        if "javascript:" in candidate.lower() or not candidate.startswith("http"):
            continue

        candidate_lower = candidate.lower()
        is_product_like = (
            "/ip/" in candidate_lower
            or "/product" in candidate_lower
            or "/products/" in candidate_lower
            or re.search(r"/(?:[^/]+-)?\d+/p(?:\?|$)", candidate_lower)
        )

        if not is_product_like and "/browse/" in candidate_lower:
            continue
        if not is_product_like and "/search" in candidate_lower:
            continue

        text = clean_text(tag.get_text(" ")).lower()
        if not is_product_like and not any(token in text for token in ("comprar", "producto", "ver producto", "agregar")):
            continue

        urls.append(candidate)
    return dedupe(urls)[:100]


def analyze_url(url):
    html, final_url = fetch_html(url)

    nextjs_products = extract_nextjs_search_products(html, final_url)
    if nextjs_products:
        return nextjs_products

    sodimac_products = extract_sodimac_products(html, final_url)
    if sodimac_products:
        return sodimac_products

    solotodo_products = extract_solotodo_products(html, final_url)
    if solotodo_products:
        return solotodo_products
    soup = BeautifulSoup(html, "lxml")
    links = candidate_product_links(soup, final_url)

    if not links:
        product = parse_product_page(final_url)
        return [product]

    products = []
    for link in links:
        try:
            product = parse_product_page(link)
            if product["images"]:
                products.append(product)
        except requests.RequestException:
            continue
        except Exception:
            continue

    if not products:
        product = parse_product_page(final_url)
        return [product]

    deduped = []
    seen = set()
    for product in products:
        key = product.get("product_id") or product.get("url")
        if key not in seen:
            deduped.append(product)
            seen.add(key)
    return deduped


def download_images_for_product(product, output_root):
    product_name = file_stem(product.get("name") or "producto")
    local_files = []

    for index, image_url in enumerate(product.get("images", [])[:20], start=1):
        try:
            response = requests.get(image_url, headers=HEADERS, timeout=25)
            response.raise_for_status()
        except Exception:
            continue

        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        suffix = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}.get(content_type, ".jpg")
        if not content_type.startswith("image/"):
            continue

        filename = f"{product_name}_{index:02d}{suffix}"
        local_path = output_root / filename
        local_path.write_bytes(response.content)
        local_files.append(str(local_path))

    return local_files


def build_product_metadata_text(products):
    lines = []
    for index, product in enumerate(products, start=1):
        name = clean_text(product.get("name") or f"Producto {index}")
        brand = clean_text(product.get("brand") or "Marca no detectada")
        price = clean_text(product.get("price") or "Sin precio")
        weight = clean_text(product.get("weight") or "Peso no detectado")
        description = clean_text(product.get("description") or "Sin descripción disponible.")
        img_paths = []
        for file_path in product.get("downloaded_files", []):
            path = Path(file_path)
            if path.exists():
                rel_path = path.relative_to(Path(__file__).resolve().parent)
                img_paths.append(rel_path.as_posix())

        lines.append(f"PRODUCTO_{index}")
        lines.append(f"nombre: {name}")
        lines.append(f"marca: {brand}")
        lines.append(f"precio: {price}")
        lines.append(f"peso: {weight}")
        lines.append(f"descripcion: {description}")
        lines.append("imagenes:")
        if img_paths:
            lines.extend(f"- {img_path}" for img_path in img_paths)
        else:
            lines.append("- sin_imagenes")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_images_zip(products):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used_names = set()
        for product in products:
            for file_path in product.get("downloaded_files", []):
                path = Path(file_path)
                if not path.is_file():
                    continue
                archive_name = path.name
                counter = 2
                while archive_name in used_names:
                    archive_name = f"{path.stem}_{counter}{path.suffix}"
                    counter += 1
                used_names.add(archive_name)
                archive.write(path, archive_name)
        archive.writestr(
            "productos_extraidos.txt",
            build_product_metadata_text(products),
        )
    return buffer.getvalue()


st.set_page_config(page_title="Descargador de fotos de productos", layout="wide")
st.title("Descargador de imágenes de productos")
st.caption("Pega una URL de un sitio web o producto y descarga las fotos con sus detalles de nombre, marca, precio, descripción y peso.")

with st.form("scraper_form"):
    url = st.text_input("URL del sitio o producto", placeholder="https://ejemplo.com/producto/123")
    submitted = st.form_submit_button("Analizar y descargar imágenes")

if submitted:
    if not url:
        st.warning("Ingresa un enlace válido.")
    else:
        try:
            with st.spinner("Analizando productos e imágenes..."):
                products = analyze_url(url)
            if not products:
                st.info("No se detectaron productos con información suficiente en esa URL.")
            else:
                OUTPUT_ROOT.mkdir(exist_ok=True)
                valid_products = []
                for product in products:
                    product["downloaded_files"] = download_images_for_product(product, OUTPUT_ROOT)
                    if product["downloaded_files"]:
                        valid_products.append(product)
                products = valid_products
                metadata_txt = build_product_metadata_text(products)
                (OUTPUT_ROOT / "productos_extraidos.txt").write_text(
                    metadata_txt,
                    encoding="utf-8",
                )
                (OUTPUT_ROOT / "productos_extraidos.json").write_text(
                    json.dumps(products, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                downloaded_count = sum(len(item["downloaded_files"]) for item in products)
                st.success(
                    f"Se identificaron {len(products)} productos y se descargaron "
                    f"{downloaded_count} imágenes."
                )

                if downloaded_count:
                    st.download_button(
                        label="Descargar imágenes en ZIP",
                        data=build_images_zip(products),
                        file_name="imagenes_productos.zip",
                        mime="application/zip",
                        type="primary",
                    )
                    st.download_button(
                        label="Descargar datos (.txt)",
                        data=metadata_txt,
                        file_name="productos_extraidos.txt",
                        mime="text/plain",
                    )

                for product in products:
                    name = product.get("name") or "Producto sin nombre"
                    price = product.get("price") or "Sin precio"
                    brand = product.get("brand") or "Marca no detectada"
                    weight = product.get("weight") or "Peso no detectado"
                    description = product.get("description") or "Sin descripción disponible."
                    image_count = len(product.get("downloaded_files", []))

                    with st.expander(f"{name} — {price} — {image_count} imagen(es)"):
                        st.write(f"Marca: {brand}")
                        st.write(f"Precio: {price}")
                        st.write(f"Peso: {weight}")
                        st.write(f"Descripción: {description}")
                        st.write(f"Ruta de imagen local: {product.get('downloaded_files', [])[0] if product.get('downloaded_files') else 'Sin imagen descargada'}")
                        images = product.get("images", [])
                        if images:
                            cols = st.columns(min(4, len(images)))
                            for col, img_url in zip(cols, images[:4]):
                                with col:
                                    st.image(img_url, width="stretch")

                        if product.get("downloaded_files"):
                            st.write("Imágenes guardadas en:")
                            for file_path in product["downloaded_files"]:
                                st.code(file_path)

                st.download_button(
                    label="Descargar archivo JSON con los resultados",
                    data=json.dumps(products, ensure_ascii=False, indent=2),
                    file_name="productos_extraidos.json",
                    mime="application/json",
                )
        except Exception as exc:
            st.error(f"Ocurrió un error: {exc}")

st.markdown("---")
st.markdown("### Cómo funciona")
st.markdown("- Pega una URL de un catálogo o producto.")
st.markdown("- Se analiza el HTML, JSON-LD y las imágenes del sitio.")
st.markdown("- Se agrupan las imágenes que pertenecen al mismo producto.")
st.markdown("- Se almacenan los datos principales: nombre, marca, precio, descripción, peso e imágenes.")
st.markdown("- Puedes bajar todo en un único archivo ZIP, además del JSON de resultados.")
