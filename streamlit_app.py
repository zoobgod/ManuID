from __future__ import annotations

import json
from datetime import datetime

import requests
import streamlit as st

DEFAULT_API_BASE = "http://127.0.0.1:8000"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _api_get(api_base: str, path: str, api_key: str) -> requests.Response:
    return requests.get(f"{api_base}{path}", headers=_headers(api_key), timeout=30)


def _api_post(api_base: str, path: str, api_key: str, payload: dict) -> requests.Response:
    return requests.post(f"{api_base}{path}", headers=_headers(api_key), data=json.dumps(payload), timeout=60)


def _show_error(response: requests.Response) -> None:
    try:
        message = response.json()
    except Exception:
        message = response.text
    st.error(f"Request failed [{response.status_code}] {message}")


st.set_page_config(page_title="ManuID Procurement", page_icon="\U0001f4ca", layout="wide")
st.title("ManuID Supplier Intelligence")
st.caption("Search suppliers by pharmacopeia product type, ingest new sources, and verify vendor records.")

with st.sidebar:
    st.header("API Connection")
    api_base = st.text_input("API Base URL", value=st.session_state.get("api_base", DEFAULT_API_BASE))
    api_key = st.text_input("API Key", value=st.session_state.get("api_key", ""), type="password")
    if st.button("Save Connection", use_container_width=True):
        st.session_state["api_base"] = api_base.rstrip("/")
        st.session_state["api_key"] = api_key.strip()
        st.success("Connection saved")

    if st.button("Test API", use_container_width=True):
        if not api_key:
            st.warning("Enter API key first")
        else:
            try:
                response = requests.get(f"{api_base.rstrip('/')}/health", timeout=10)
                if response.ok:
                    st.success("Backend reachable")
                else:
                    st.warning(f"Health check failed: {response.status_code}")
            except requests.RequestException as exc:
                st.error(f"Could not reach backend: {exc}")

api_base = st.session_state.get("api_base", api_base).rstrip("/")
api_key = st.session_state.get("api_key", api_key).strip()

if not api_key:
    st.info("Set API key in the sidebar to start.")
    st.stop()

tab_search, tab_ingest, tab_review = st.tabs(["Search Vendors", "Ingest Source", "Vendor Review"])

with tab_search:
    st.subheader("Vendor Search")
    with st.form("search_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            product_type_query = st.text_input("Product Type", placeholder="e.g., USP reference standards")
            country = st.text_input("Country Filter (optional)")
        with col2:
            region = st.text_input("Region Filter (optional)")
            certifications_raw = st.text_input("Certifications (comma separated)", placeholder="GMP, ISO 9001")
        with col3:
            role = st.selectbox(
                "Role",
                options=["", "PRIMARY_MANUFACTURER", "AUTHORIZED_DISTRIBUTOR", "RESELLER"],
                index=0,
            )
            limit = st.number_input("Limit", min_value=1, max_value=100, value=25)

        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        if not product_type_query.strip():
            st.warning("Product type is required")
        else:
            payload = {
                "product_type_query": product_type_query.strip(),
                "country": country.strip() or None,
                "region": region.strip() or None,
                "certifications": [x.strip() for x in certifications_raw.split(",") if x.strip()],
                "role": role or None,
                "limit": int(limit),
            }

            try:
                response = _api_post(api_base, "/v1/search/vendors", api_key, payload)
            except requests.RequestException as exc:
                st.error(f"Search failed: {exc}")
            else:
                if not response.ok:
                    _show_error(response)
                else:
                    data = response.json()
                    st.success(f"Found {len(data.get('data', []))} vendor(s)")
                    if data.get("product_type"):
                        st.caption(f"Matched product type: {data['product_type']['name']}")

                    rows = []
                    for item in data.get("data", []):
                        contacts = item.get("contacts", [])
                        first_contact = contacts[0] if contacts else {}
                        rows.append(
                            {
                                "id": item["id"],
                                "name": item["name"],
                                "country": item.get("hq_country"),
                                "website": item.get("website"),
                                "score": item.get("score"),
                                "confidence": item.get("confidence_score"),
                                "status": item.get("status"),
                                "email": first_contact.get("email"),
                                "phone": first_contact.get("phone"),
                            }
                        )

                    if rows:
                        st.dataframe(rows, use_container_width=True)
                        with st.expander("Scoring Rationale", expanded=False):
                            for item in data.get("data", []):
                                st.markdown(f"**{item['name']}**")
                                for reason in item.get("score_reasons", []):
                                    st.write(f"- {reason}")
                    else:
                        st.info("No matching vendors")

with tab_ingest:
    st.subheader("Ingest Vendors From URL")
    st.caption("Only allowlisted domains can be scraped. Update SCRAPE_ALLOWLIST in your backend env to add more domains.")

    col_left, col_right = st.columns([2, 1])
    with col_left:
        with st.form("ingest_form"):
            source_url = st.text_input("Source URL", placeholder="https://example.com/vendor-list")
            source_name = st.text_input("Source Name", value="User Source")
            product_type = st.text_input("Product Type", placeholder="e.g., Pharmacopoeial Excipients")
            role = st.selectbox("Link Role", options=["AUTHORIZED_DISTRIBUTOR", "PRIMARY_MANUFACTURER", "RESELLER"])
            dry_run = st.checkbox("Dry run (preview only)", value=True)
            ingest_submit = st.form_submit_button("Run Ingestion", type="primary")

        if ingest_submit:
            if not source_url.strip() or not product_type.strip():
                st.warning("Source URL and Product Type are required")
            else:
                payload = {
                    "source_url": source_url.strip(),
                    "source_name": source_name.strip() or "User Source",
                    "product_type_query": product_type.strip(),
                    "role": role,
                    "dry_run": dry_run,
                }
                try:
                    response = _api_post(api_base, "/v1/ingestion/url", api_key, payload)
                except requests.RequestException as exc:
                    st.error(f"Ingestion failed: {exc}")
                else:
                    if not response.ok:
                        _show_error(response)
                    else:
                        result = response.json()
                        st.success(result.get("message", "Ingestion completed"))
                        st.json(result)

    with col_right:
        st.markdown("**Default Source Catalog**")
        try:
            sources_response = _api_get(api_base, "/v1/source-catalog", api_key)
            if sources_response.ok:
                for item in sources_response.json().get("data", []):
                    st.write(f"- {item['name']}: {item['url']}")
            else:
                _show_error(sources_response)
        except requests.RequestException as exc:
            st.warning(f"Could not load catalog: {exc}")

with tab_review:
    st.subheader("Vendor Verification")
    vendor_id = st.number_input("Vendor ID", min_value=1, value=1, step=1)

    if st.button("Load Vendor", use_container_width=False):
        try:
            response = _api_get(api_base, f"/v1/vendors/{int(vendor_id)}", api_key)
        except requests.RequestException as exc:
            st.error(f"Failed to load vendor: {exc}")
        else:
            if not response.ok:
                _show_error(response)
            else:
                data = response.json()
                vendor = data["vendor"]
                st.markdown(f"### {vendor['name']}")
                st.write(f"Country: {vendor.get('hq_country') or '-'}")
                st.write(f"Website: {vendor.get('website') or '-'}")
                st.write(f"Confidence: {vendor.get('confidence_score')} | State: {vendor.get('verification_state')}")
                st.write(f"Last verified: {vendor.get('last_verified_at') or '-'}")

                st.markdown("**Product Types**")
                for pt in data.get("product_types", []):
                    st.write(f"- {pt['name']}")

                st.markdown("**Evidence URLs**")
                for url in data.get("evidence_urls", []):
                    st.write(f"- {url}")

                st.markdown("**Contacts**")
                st.dataframe(vendor.get("contacts", []), use_container_width=True)

    st.markdown("### Manual Verification Update")
    with st.form("verify_form"):
        state = st.selectbox("Verification State", options=["UNVERIFIED", "AUTO_VERIFIED", "HUMAN_VERIFIED"])
        score = st.slider("Confidence Score", min_value=0.0, max_value=1.0, value=0.8, step=0.01)
        notes = st.text_input("Notes", placeholder="Checked against official supplier contact page")
        verify_submit = st.form_submit_button("Submit Verification", type="primary")

    if verify_submit:
        payload = {
            "verification_state": state,
            "confidence_score": score,
            "notes": notes.strip() or None,
        }
        try:
            response = _api_post(api_base, f"/v1/vendors/{int(vendor_id)}/verify", api_key, payload)
        except requests.RequestException as exc:
            st.error(f"Verification request failed: {exc}")
        else:
            if not response.ok:
                _show_error(response)
            else:
                item = response.json()
                st.success(f"Vendor updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                st.json(item)
