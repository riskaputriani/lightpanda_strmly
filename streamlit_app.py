import streamlit as st
import asyncio
import subprocess
from src.setup import install_google_chrome
from src.cf_solver.solver_zendriver import CloudflareSolver, get_chrome_user_agent
import shutil
from pathlib import Path

# Install Google Chrome and cache the result
install_google_chrome()

@st.cache_resource
def get_chrome_executable_path() -> str:
    """
    Get the path to the Google Chrome executable.
    """
    return shutil.which("google-chrome") or shutil.which("chrome")

async def process_url(url: str, get_title: bool, get_screenshot: bool, get_html: bool, download_file: bool):
    """
    Process a URL to get title, screenshot, HTML, and/or download a file.
    """
    user_agent = get_chrome_user_agent()
    results = {}
    async with CloudflareSolver(
        cdp_url=None,
        user_agent=user_agent,
        timeout=30,
        headless=True,
        browser_executable_path=get_chrome_executable_path(),
    ) as solver:
        await solver.driver.get(url)
        all_cookies = await solver.get_cookies()
        clearance_cookie = solver.extract_clearance_cookie(all_cookies)
        if clearance_cookie is None:
            await solver.set_user_agent_metadata(await solver.get_user_agent())
            await solver.solve_challenge()
            all_cookies = await solver.get_cookies()
            clearance_cookie = solver.extract_clearance_cookie(all_cookies)
        
        results["clearance_cookie"] = clearance_cookie
        
        if get_title:
            results["title"] = await solver.driver.main_tab.get_title()

        if get_screenshot:
            screenshot_path = Path("screenshot.png")
            await solver.driver.main_tab.save_screenshot(str(screenshot_path))
            results["screenshot_path"] = screenshot_path

        if get_html:
            html_path = Path("response.html")
            html_content = await solver.driver.main_tab.get_content()
            html_path.write_text(html_content, encoding="utf-8")
            results["html_path"] = html_path
            
        if download_file:
            user_agent = await solver.get_user_agent()
            cookie_string = "; ".join(
                f'{cookie["name"]}={cookie["value"]}' for cookie in all_cookies
            )
            results["user_agent"] = user_agent
            results["cookie_string"] = cookie_string

    return results

st.title("Chrome Downloader")

mode = st.radio("Select mode:", ("Download File", "Get Clearance Cookie"))

if mode == "Get Clearance Cookie":
    url = st.text_input("Enter the URL to solve the challenge for:")
    if st.button("Get Clearance Cookie"):
        if url:
            with st.spinner("Solving Cloudflare challenge..."):
                results = asyncio.run(process_url(url, False, False, False, False))
                cookie = results.get("clearance_cookie")
                if cookie:
                    st.success("Successfully retrieved Cloudflare clearance cookie!")
                    st.json(cookie)
                else:
                    st.error("Failed to retrieve Cloudflare clearance cookie.")
        else:
            st.warning("Please enter a URL.")
else: # Download File
    url = st.text_input("Enter the URL of the file to download:")
    
    get_title = st.checkbox("Get Title")
    get_screenshot = st.checkbox("Take Screenshot")
    get_html = st.checkbox("Get HTML")

    if st.button("Process URL"):
        if url:
            with st.spinner("Processing URL..."):
                results = asyncio.run(process_url(url, get_title, get_screenshot, get_html, True))
                
                if get_title:
                    st.subheader("Page Title")
                    st.write(results.get("title"))
                
                if get_screenshot:
                    st.subheader("Screenshot")
                    screenshot_path = results.get("screenshot_path")
                    if screenshot_path and screenshot_path.exists():
                        st.image(str(screenshot_path))
                        with open(screenshot_path, "rb") as f:
                            st.download_button("Download Screenshot", f, "screenshot.png")

                if get_html:
                    st.subheader("HTML Content")
                    html_path = results.get("html_path")
                    if html_path and html_path.exists():
                        with open(html_path, "rb") as f:
                            st.download_button("Download HTML", f, "response.html")

                # Download the file using wget
                cookie = results.get("clearance_cookie")
                if cookie:
                    st.subheader("File Download")
                    # Create a downloads directory if it doesn't exist
                    downloads_dir = Path("downloads")
                    downloads_dir.mkdir(exist_ok=True)
                    
                    # Get the filename from the URL
                    filename = url.split("/")[-1] or "downloaded_file"
                    filepath = downloads_dir / filename

                    try:
                        wget_command = [
                            "wget",
                            "--header",
                            f'Cookie: {results.get("cookie_string")}',
                            "--header",
                            f'User-Agent: {results.get("user_agent")}',
                            "-O",
                            str(filepath),
                            url,
                        ]
                        subprocess.run(wget_command, check=True, capture_output=True)
                        st.success(f"File downloaded successfully to {filepath}")
                        
                        with open(filepath, "rb") as f:
                            st.download_button(
                                label="Download " + filename,
                                data=f,
                                file_name=filename,
                            )
                    except subprocess.CalledProcessError as e:
                        st.error(f"Failed to download file with wget. Error: {e.stderr.decode()}")
                else:
                    st.error("Failed to retrieve Cloudflare clearance cookie for download.")
        else:
            st.warning("Please enter a URL.")