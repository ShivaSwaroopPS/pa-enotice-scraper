import re
import asyncio
import httpx
from bs4 import BeautifulSoup
import pandas as pd
import urllib3
from datetime import datetime
import streamlit as st

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="PA eNotice Processor", layout="wide")
st.title("📩 PA eNotice → CSV Exporter")

# --- How to Use section ---
with st.expander("ℹ️ How to Use", expanded=True):
    st.markdown("""
    1. **Open the PA eNotice email in Outlook**.  
    2. **Copy the entire email body** (starting from *“The following Permit Applications have changed…”*).  
    3. **Paste it into the text box below**.  
    4. Click **Process** → wait a few seconds.  
    5. Click **Download CSV** to save the results.  
    6. Open the file in Excel → two columns:  
       - **Mail Data** = email content  
       - **API** = Permit #, Authorization Type, Status  
    """)

# --- Input area ---
email_text = st.text_area("Paste the full PA eNotice email body here:", height=400)

if st.button("Process"):
    if not email_text.strip():
        st.error("⚠️ Please paste the email body first.")
    else:
        # === Extract header line ===
        lines = email_text.strip().splitlines()
        header_line = lines[0].strip() if lines else "The following Permit Applications have changed"

        # extract date from header → filename
        date_match = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", header_line)
        if date_match:
            try:
                parsed_date = datetime.strptime(date_match.group(1), "%B %d, %Y")
                output_filename = parsed_date.strftime("%d-%m-%Y") + ".csv"
            except Exception:
                output_filename = "PA_eNotice.csv"
        else:
            output_filename = "PA_eNotice.csv"

        st.write(f"📋 Header: `{header_line}`")
        st.write(f"💾 Output filename: `{output_filename}`")

        # === Split into blocks ===
        blocks = re.split(r"(?=Authorization \d+:)", email_text.strip())
        blocks = [b for b in blocks if b.strip().startswith("Authorization")]

        st.info(f"Found **{len(blocks)}** authorization blocks")

        # === Async Scraper ===
        async def fetch_efacts(client, auth_id):
            url = f"https://www.ahs.dep.pa.gov/eFACTSWeb/searchResults_singleAuth.aspx?AuthID={auth_id}"
            try:
                resp = await client.get(url, timeout=30.0)
                soup = BeautifulSoup(resp.text, "html.parser")

                permit_number = soup.find("span", id="ContentPlaceHolder2_DetailsView1_lblPermitNumber")
                auth_type = soup.find("span", id="ContentPlaceHolder2_DetailsView1_lblAuthType")
                status = soup.find("span", id="ContentPlaceHolder2_DetailsView1_lblStatus")

                permit_number = f"37-{permit_number.text.strip()}" if permit_number else ""
                auth_type = auth_type.text.strip() if auth_type else ""
                status = status.text.strip() if status else ""

                return [permit_number, auth_type, status]
            except Exception as e:
                return ["", "", f"Error: {e}"]

        async def process_blocks():
            rows = []
            async with httpx.AsyncClient(verify=False) as client:
                coros, mail_blocks = [], []
                for block in blocks:
                    match = re.search(r"Authorization\s+(\d+)", block)
                    if not match:
                        continue
                    auth_id = match.group(1)
                    mail_blocks.append(block.splitlines())
                    coros.append(fetch_efacts(client, auth_id))

                results = await asyncio.gather(*coros)

                for mail_lines, api_lines in zip(mail_blocks, results):
                    if len(mail_lines) > len(api_lines):
                        api_lines.extend([""] * (len(mail_lines) - len(api_lines)))
                    for ml, al in zip(mail_lines, api_lines):
                        rows.append([ml, al])
                    rows.append(["", ""])  # separator

            df = pd.DataFrame(rows, columns=[header_line, "API"])
            # add blank row after header
            blank_row = pd.DataFrame([["", ""]], columns=df.columns)
            df = pd.concat([blank_row, df], ignore_index=True)
            return df

        with st.spinner("⏳ Processing, please wait..."):
            df = asyncio.run(process_blocks())

        st.success("✅ Processing complete!")

        # Show preview
        st.dataframe(df.head(30))

        # Download button
        csv_data = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name=output_filename,
            mime="text/csv"
        )
