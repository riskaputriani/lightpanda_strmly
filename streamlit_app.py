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

async def get_clearance_cookie(url: str):
    """
    Get the Cloudflare clearance cookie and user agent for a given URL.
    """
    user_agent = get_chrome_user_agent()
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
        
        user_agent = await solver.get_user_agent()
        cookie_string = "; ".join(
            f'{cookie["name"]}={cookie["value"]}' for cookie in all_cookies
        )
        return clearance_cookie, user_agent, cookie_string

st.title("Chrome Downloader")

mode = st.radio("Select mode:", ("Download File", "Get Clearance Cookie"))

if mode == "Get Clearance Cookie":
    url = st.text_input("Enter the URL to solve the challenge for:")
    if st.button("Get Clearance Cookie"):
        if url:
            with st.spinner("Solving Cloudflare challenge..."):
                cookie, _, _ = asyncio.run(get_clearance_cookie(url))
                if cookie:
                    st.success("Successfully retrieved Cloudflare clearance cookie!")
                    st.json(cookie)
                else:
                    st.error("Failed to retrieve Cloudflare clearance cookie.")
        else:
            st.warning("Please enter a URL.")
else: # Download File
    url = st.text_input("Enter the URL of the file to download:")
    if st.button("Download"):
        if url:
            with st.spinner("Solving Cloudflare challenge and downloading file..."):
                cookie, user_agent, cookie_string = asyncio.run(get_clearance_cookie(url))
                if cookie:
                    st.success("Successfully retrieved Cloudflare clearance cookie!")
                    
                    # Create a downloads directory if it doesn't exist
                    downloads_dir = Path("downloads")
                    downloads_dir.mkdir(exist_ok=True)
                    
                    # Get the filename from the URL
                    filename = url.split("/")[-1]
                    filepath = downloads_dir / filename

                    # Download the file using wget
                    try:
                        wget_command = [
                            "wget",
                            "--header",
                            f"Cookie: {cookie_string}",
                            "--header",
                            f"User-Agent: {user_agent}",
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
                    st.error("Failed to retrieve Cloudflare clearance cookie.")
        else:
            st.warning("Please enter a URL.")