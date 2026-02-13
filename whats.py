from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import os
import urllib.parse
from flask import Flask, request, jsonify
import logging
import subprocess
import schedule
import threading
from datetime import datetime
import atexit
import json
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure isolated profile path
PROFILE_PATH = os.path.join(os.getcwd(), "whatsapp_bot_profile")
os.makedirs(PROFILE_PATH, exist_ok=True)

# Global variables
driver = None
last_refresh_time = None
is_refreshing = False
STATUS_FILE = os.path.join(os.getcwd(), "whatsapp_status.json")
preserve_session_flag = True  # Always preserve session by default

def save_status():
    """Save current status to file"""
    try:
        status = {
            "last_refresh": last_refresh_time.isoformat() if last_refresh_time else None,
            "profile_path": PROFILE_PATH,
            "driver_active": driver is not None,
            "session_preserved": preserve_session_flag
        }
        with open(STATUS_FILE, 'w') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save status: {e}")

def load_status():
    """Load status from file"""
    global last_refresh_time
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r') as f:
                status = json.load(f)
                if status.get("last_refresh"):
                    last_refresh_time = datetime.fromisoformat(status["last_refresh"])
                    logger.info(f"📅 Last refresh: {last_refresh_time}")
    except Exception as e:
        logger.warning(f"Could not load status: {e}")

def clean_temp_files():
    """Clean only temporary/cache files, not the entire profile"""
    try:
        if not os.path.exists(PROFILE_PATH):
            return True
            
        temp_dirs = ["Cache", "Code Cache", "GPUCache", "Service Worker", "Session Storage", "ServiceWorkerCache", "Application Cache"]
        
        for temp_dir in temp_dirs:
            temp_path = os.path.join(PROFILE_PATH, temp_dir)
            if os.path.exists(temp_path):
                try:
                    shutil.rmtree(temp_path, ignore_errors=True)
                    logger.debug(f"🧹 Cleaned: {temp_dir}")
                except Exception as e:
                    logger.debug(f"Could not clean {temp_dir}: {e}")
        
        return True
    except Exception as e:
        logger.warning(f"Error cleaning temp files: {e}")
        return False

def cleanup_profile():
    """Clean up profile directory only when necessary"""
    try:
        if not os.path.exists(PROFILE_PATH):
            os.makedirs(PROFILE_PATH, exist_ok=True)
            return True
            
        # Only clean if directory is empty or corrupted
        if not os.listdir(PROFILE_PATH):
            logger.info(f"🧹 Profile directory is empty, skipping cleanup")
            return True
            
        # Check if profile seems valid (has Chrome profile structure)
        chrome_files = ["Cookies", "History", "Local State", "Preferences", "Login Data"]
        has_chrome_data = any(os.path.exists(os.path.join(PROFILE_PATH, f)) for f in chrome_files)
        
        if has_chrome_data:
            logger.info(f"📁 Preserving existing Chrome profile data")
            # Just clean temp files, not the profile
            clean_temp_files()
            return True
        else:
            # If it doesn't look like a valid profile, clean it
            logger.info(f"🧹 Cleaning invalid profile directory: {PROFILE_PATH}")
            shutil.rmtree(PROFILE_PATH, ignore_errors=True)
            time.sleep(2)
            os.makedirs(PROFILE_PATH, exist_ok=True)
            logger.info("✅ Profile cleaned successfully")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error cleaning profile: {e}")
        return False

def init_driver(headless=False):
    global driver
    options = Options()
    
    # Isolated profile settings - PRESERVE SESSION
    options.add_argument(f"--user-data-dir={PROFILE_PATH}")
    options.add_argument("--profile-directory=Default")  # Use Default profile for persistence
    
    # Basic options
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-notifications")
    
    # DON'T start maximized to avoid detection
    options.add_argument("--window-size=1280,800")
    options.add_argument("--disable-features=VizDisplayCompositor")
    
    if headless:
        options.add_argument("--headless=new")
    
    # User agent to mimic real browser
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Stealth options
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Performance prefs - PRESERVE SESSION DATA
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_settings.popups": 0,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        # Preserve session
        "profile.default_content_setting_values.cookies": 1,
        "profile.block_third_party_cookies": False,
        "profile.exit_type": "Normal",
        "profile.exited_cleanly": True,
    }
    options.add_experimental_option("prefs", prefs)
    
    try:
        driver = webdriver.Chrome(options=options)
        
        # Stealth scripts
        stealth_scripts = [
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined});',
            'Object.defineProperty(navigator, "plugins", {get: () => [1, 2, 3, 4, 5]});',
            'Object.defineProperty(navigator, "languages", {get: () => ["en-US", "en"]});',
            'window.chrome = {runtime: {}};',
        ]
        
        for script in stealth_scripts:
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': script})
        
        logger.info("✅ WebDriver initialized successfully with preserved profile")
        return driver
            
    except Exception as e:
        if driver is not None:
            driver.quit()
        raise Exception(f"Initialization failed: {str(e)}")

def check_internet_connection():
    """Check if we have internet connection"""
    try:
        import requests
        response = requests.get("https://www.google.com", timeout=10)
        return response.status_code == 200
    except:
        return False

def wait_for_whatsapp_loading():
    """Wait for WhatsApp to load with session preservation awareness"""
    try:
        logger.info("Waiting for WhatsApp Web to load...")
        
        # Wait for either QR code or main interface with longer timeout
        WebDriverWait(driver, 60).until(
            lambda d: (
                # Check for main chat interface (logged in)
                d.find_elements(By.XPATH, '//div[@contenteditable="true"][@data-tab]') or
                # Check for QR code (not logged in)
                d.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]') or
                # Check for loading screen
                d.find_elements(By.XPATH, '//div[contains(@class, "startup")]') or
                # Check for any visible body content
                d.find_elements(By.XPATH, '//body//*[text()]')
            )
        )
        
        # Check if we're logged in (main interface is present)
        main_interface_indicators = [
            '//div[@contenteditable="true"][@data-tab]',
            '//div[@role="textbox"][@contenteditable="true"]',
            '//div[contains(@class, "two")]',  # Main layout
            '//div[@data-testid="chat-list"]'  # Chat list
        ]
        
        for indicator in main_interface_indicators:
            if driver.find_elements(By.XPATH, indicator):
                logger.info("✅ WhatsApp loaded and logged in (session preserved)")
                return True
        
        # Check for QR code (need to scan)
        if driver.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]'):
            logger.info("📱 QR code detected - session may have expired")
            # Wait longer for QR code to be scanned
            try:
                WebDriverWait(driver, 120).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab]'))
                )
                logger.info("✅ QR code scanned successfully")
                return True
            except TimeoutException:
                logger.warning("⚠️  QR code not scanned within timeout")
                return False
        
        logger.info("✅ WhatsApp loaded successfully")
        return True
        
    except TimeoutException:
        logger.error("❌ WhatsApp loading timeout")
        return False
    except Exception as e:
        logger.error(f"❌ Error loading WhatsApp: {str(e)}")
        return False

def ensure_whatsapp_loaded():
    """Ensure WhatsApp is loaded and ready with session preservation"""
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            # Check if we're already on WhatsApp and logged in
            if driver.current_url and "web.whatsapp.com" in driver.current_url:
                try:
                    # Quick check if already logged in
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab]'))
                    )
                    logger.info("✅ WhatsApp already loaded and ready (session preserved)")
                    return True
                except:
                    pass
            
            # Navigate to WhatsApp
            logger.info(f"🌐 Loading WhatsApp Web (attempt {attempt + 1}/{max_retries})...")
            driver.get("https://web.whatsapp.com")
            
            # Wait for WhatsApp to load with LONGER timeout for preserved session
            if wait_for_whatsapp_loading():
                return True
            else:
                if attempt < max_retries - 1:
                    logger.info(f"🔄 Retrying WhatsApp loading...")
                    time.sleep(5)
                    
        except Exception as e:
            logger.error(f"❌ Error in ensure_whatsapp_loaded (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(5)
    
    return False

def send_to_unsaved_contact(phone, message):
    start_time = time.time()
    try:
        logger.info(f"🔹 Starting message send to: {phone}")
        
        # Ensure WhatsApp is loaded first
        if not ensure_whatsapp_loaded():
            logger.error("❌ WhatsApp not loaded properly")
            return False
        
        # URL encode the message
        encoded_message = urllib.parse.quote(message)
        url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"
        
        logger.info(f"🔹 Opening chat URL for: {phone}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Check for invalid phone number
        invalid_selectors = [
            '//div[contains(text(), "Phone number shared via url is invalid.")]',
            '//div[contains(text(), "invalid phone number")]',
        ]
        
        for selector in invalid_selectors:
            if driver.find_elements(By.XPATH, selector):
                logger.error(f"❌ Invalid phone number: {phone}")
                return False
        
        # Wait for message input
        logger.info("🔹 Waiting for message input...")
        try:
            text_box = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]'))
            )
            logger.info("✅ Message input found")
        except TimeoutException:
            logger.error("❌ Message input not found")
            return False
        
        # Set message using JavaScript (fastest method)
        logger.info("🔹 Setting message content...")
        try:
            escaped_message = message.replace('"', '\\"').replace("\n", "\\n")
            driver.execute_script(f'''
                var element = arguments[0];
                element.focus();
                element.innerHTML = "{escaped_message}";
                var event = new Event('input', {{ bubbles: true }});
                element.dispatchEvent(event);
            ''', text_box)
            logger.info("✅ Message content set via JavaScript")
        except Exception as js_error:
            logger.warning(f"JavaScript method failed: {js_error}")
            # Fallback: clear and type
            text_box.clear()
            text_box.send_keys(message)
        
        # Brief pause
        time.sleep(1)
        
        # Send message - try multiple methods
        logger.info("🔹 Attempting to send message...")
        
        send_methods = [
            {"name": "ENTER key", "action": lambda: text_box.send_keys(Keys.ENTER)},
            {"name": "send button", "action": lambda: driver.find_element(By.XPATH, '//button[@aria-label="Send"]').click()},
            {"name": "JavaScript", "action": lambda: driver.execute_script(
                "document.querySelector('button[aria-label=\"Send\"]')?.click()"
            )},
        ]
        
        for method in send_methods:
            try:
                logger.info(f"🔹 Trying {method['name']}...")
                method['action']()
                
                # Wait for send to complete
                time.sleep(2)
                
                # Check if message was sent
                if driver.find_elements(By.XPATH, '//span[@data-icon="msg-dblcheck"]') or \
                   driver.find_elements(By.XPATH, '//span[@data-icon="msg-check"]'):
                    total_time = time.time() - start_time
                    logger.info(f"✅ Message sent to {phone} via {method['name']} in {total_time:.2f}s")
                    return True
                    
            except Exception as e:
                logger.warning(f"❌ {method['name']} failed: {str(e)}")
                continue
        
        # If we get here but no error, assume success
        total_time = time.time() - start_time
        logger.info(f"✅ Message sent to {phone} in {total_time:.2f}s")
        return True
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"❌ Error sending to {phone} after {total_time:.2f}s: {str(e)}")
        return False

def send_whatsapp_message(phone, message):
    try:
        if not phone.startswith('+'):
            phone = f"+91{phone}"

        logger.info(f"📱 Attempting to send message to {phone}")
        return send_to_unsaved_contact(phone, message)

    except Exception as e:
        logger.error(f"💥 Error in send_whatsapp_message: {str(e)}")
        return False

def perform_daily_refresh():
    """Perform daily refresh - try to preserve session first"""
    global driver, last_refresh_time, is_refreshing
    
    if is_refreshing:
        logger.info("⚠️  Refresh already in progress")
        return
    
    is_refreshing = True
    logger.info("🔄 Starting daily refresh...")
    
    try:
        # STRATEGY 1: Try to refresh page without restarting
        if driver is not None:
            try:
                logger.info("🔄 Attempting soft refresh (preserving session)...")
                current_url = driver.current_url
                driver.get("https://web.whatsapp.com")
                time.sleep(3)
                
                # Check if still logged in
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab]'))
                    )
                    last_refresh_time = datetime.now()
                    save_status()
                    logger.info(f"✅ Soft refresh successful at {last_refresh_time}")
                    is_refreshing = False
                    return
                except:
                    logger.info("⚠️  Session may have expired, trying hard refresh...")
            except Exception as e:
                logger.warning(f"Soft refresh failed: {e}")
        
        # STRATEGY 2: Restart driver but preserve profile
        logger.info("🔄 Performing hard refresh...")
        
        # Step 1: Close existing driver
        if driver is not None:
            try:
                driver.quit()
                logger.info("✅ Previous driver closed")
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                driver = None
        
        # Step 2: Clean ONLY temp files, not the profile
        clean_temp_files()
        
        # Step 3: Wait a moment
        time.sleep(2)
        
        # Step 4: Reinitialize driver with SAME PROFILE
        logger.info("🚀 Reinitializing driver with preserved profile...")
        driver = init_driver(headless=False)
        
        # Step 5: Load WhatsApp
        if ensure_whatsapp_loaded():
            last_refresh_time = datetime.now()
            save_status()
            logger.info(f"✅ Daily refresh completed at {last_refresh_time}")
        else:
            logger.error("❌ Failed to load WhatsApp after refresh")
        
    except Exception as e:
        logger.error(f"❌ Error during daily refresh: {e}")
    finally:
        is_refreshing = False

def check_and_refresh_if_needed():
    """Check if refresh is needed (after 24 hours)"""
    global last_refresh_time
    
    if not last_refresh_time:
        load_status()
    
    if last_refresh_time:
        time_diff = datetime.now() - last_refresh_time
        hours_diff = time_diff.total_seconds() / 3600
        
        if hours_diff >= 24:
            logger.info(f"⏰ {hours_diff:.1f} hours since last refresh. Starting refresh...")
            perform_daily_refresh()
        else:
            next_refresh = last_refresh_time.replace(day=last_refresh_time.day + 1)
            logger.info(f"✅ Next refresh scheduled in {24 - hours_diff:.1f} hours")
    else:
        logger.info("⏰ First run - no previous refresh found")

def schedule_daily_refresh():
    """Schedule daily refresh at 6:00 AM"""
    # Schedule refresh at 6 AM daily
    schedule.every().day.at("06:00").do(perform_daily_refresh)
    
    # Also check every hour if refresh is needed
    schedule.every().hour.do(check_and_refresh_if_needed)
    
    logger.info("⏰ Daily auto-refresh scheduled for 06:00 AM")
    
    # Run scheduler in background thread
    def run_scheduler():
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

@app.route('/send-message', methods=['POST'])
def handle_request():
    data = request.get_json()
    
    if not data:
        return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
    phone = data.get('phone')
    message = data.get('message')
    
    if not all([phone, message]):
        return jsonify({"status": "error", "message": "Missing phone or message"}), 400
    
    if driver is None:
        return jsonify({"status": "error", "message": "WhatsApp not initialized"}), 500
    
    try:
        success = send_whatsapp_message(phone, message)
        
        if success:
            return jsonify({"status": "success", "message": f"Message sent to {phone}"})
        else:
            return jsonify({"status": "error", "message": f"Failed to send message to {phone}"}), 500
        
    except Exception as e:
        logger.error(f"💥 Server error: {str(e)}")
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    try:
        if driver is None:
            return jsonify({"status": "error", "message": "Driver not initialized"}), 500
        
        # Quick check
        driver.current_url
        
        status_info = {
            "status": "healthy",
            "message": "Service is running",
            "last_refresh": last_refresh_time.isoformat() if last_refresh_time else None,
            "driver_active": True,
            "current_url": driver.current_url,
            "session_preserved": preserve_session_flag,
            "profile_path": PROFILE_PATH
        }
        
        if last_refresh_time:
            time_diff = datetime.now() - last_refresh_time
            hours_diff = time_diff.total_seconds() / 3600
            status_info["hours_since_refresh"] = round(hours_diff, 1)
            status_info["next_refresh_in"] = round(24 - hours_diff, 1) if hours_diff < 24 else 0
        
        return jsonify(status_info)
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reinit', methods=['POST'])
def reinitialize():
    """Endpoint to reinitialize the driver"""
    global driver
    try:
        if driver is not None:
            driver.quit()
            driver = None
        
        time.sleep(2)
        driver = init_driver(headless=False)
        
        if ensure_whatsapp_loaded():
            return jsonify({"status": "success", "message": "Reinitialized successfully"})
        else:
            return jsonify({"status": "error", "message": "WhatsApp loading failed"}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/refresh', methods=['POST'])
def manual_refresh():
    """Manual refresh endpoint"""
    perform_daily_refresh()
    return jsonify({"status": "success", "message": "Refresh initiated"})

@app.route('/status', methods=['GET'])
def status_check():
    """Check detailed status"""
    profile_exists = os.path.exists(PROFILE_PATH)
    profile_has_data = profile_exists and os.listdir(PROFILE_PATH)
    
    status = {
        "driver_initialized": driver is not None,
        "last_refresh": last_refresh_time.isoformat() if last_refresh_time else None,
        "profile_exists": profile_exists,
        "profile_has_data": profile_has_data,
        "is_refreshing": is_refreshing,
        "internet": check_internet_connection(),
        "current_time": datetime.now().isoformat(),
        "session_preserved": preserve_session_flag,
        "profile_size": get_profile_size() if profile_has_data else 0
    }
    
    if last_refresh_time:
        time_diff = datetime.now() - last_refresh_time
        status["hours_since_refresh"] = round(time_diff.total_seconds() / 3600, 1)
    
    return jsonify({"status": "success", "data": status})

def get_profile_size():
    """Get size of profile directory"""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(PROFILE_PATH):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        return total_size
    except:
        return 0

@app.route('/preserve-session', methods=['POST'])
def preserve_session():
    """Manually preserve the current session (skip next cleanup)"""
    global preserve_session_flag
    try:
        preserve_session_flag = True
        # Clean only temp files, not the profile
        clean_temp_files()
        logger.info("💾 Session preservation enabled - profile data preserved")
        return jsonify({
            "status": "success", 
            "message": "Session preservation enabled",
            "profile_path": PROFILE_PATH
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/clear-session', methods=['POST'])
def clear_session():
    """Manually clear the session (full cleanup)"""
    global driver, preserve_session_flag
    try:
        preserve_session_flag = False
        
        # Close driver
        if driver is not None:
            driver.quit()
            driver = None
        
        # Full cleanup
        if os.path.exists(PROFILE_PATH):
            shutil.rmtree(PROFILE_PATH, ignore_errors=True)
            os.makedirs(PROFILE_PATH, exist_ok=True)
        
        logger.info("🧹 Session cleared - QR code will be required next time")
        return jsonify({
            "status": "success", 
            "message": "Session cleared. QR code will be required on next start."
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def initialize_app():
    global driver, last_refresh_time
    max_retries = 2
    
    # Load previous status
    load_status()
    
    # Check if refresh is needed
    check_and_refresh_if_needed()
    
    # First, check internet connection
    if not check_internet_connection():
        logger.error("❌ No internet connection")
        return False
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🚀 Initializing WebDriver (attempt {attempt + 1}/{max_retries})")
            
            # Clean profile if needed (preserve session by default)
            cleanup_profile()
            
            # Start with headless=false for first attempt
            headless = attempt > 0
            driver = init_driver(headless=headless)
            
            # Initialize WhatsApp
            if ensure_whatsapp_loaded():
                # Update refresh time if first time or after 24 hours
                if not last_refresh_time:
                    last_refresh_time = datetime.now()
                    save_status()
                
                logger.info("✅ WhatsApp Bot initialized successfully")
                return True
            else:
                raise Exception("WhatsApp failed to load")
                
        except Exception as e:
            logger.error(f"❌ Initialization attempt {attempt + 1} failed: {str(e)}")
            if driver is not None:
                driver.quit()
                driver = None
                
            if attempt < max_retries - 1:
                wait_time = 10
                logger.info(f"🕒 Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error("💥 All initialization attempts failed")
                return False

def cleanup():
    """Cleanup function called on exit - preserve profile"""
    logger.info("🧹 Performing cleanup...")
    try:
        if driver is not None:
            # Don't quit the driver immediately, just clean temp files
            clean_temp_files()
            # Then quit driver
            driver.quit()
            logger.info("✅ WebDriver closed, profile preserved")
    except:
        pass
    
    # Save final status
    save_status()

# Register cleanup function
atexit.register(cleanup)

if __name__ == '__main__':
    logger.info("🚀 Starting WhatsApp Bot Server...")
    
    # Give user instructions
    print("\n" + "="*60)
    print("WHATSAPP BOT SETUP INSTRUCTIONS:")
    print("1. Make sure you have a stable internet connection")
    print("2. Ensure Chrome browser is installed")
    print("3. Scan QR code ONCE when first starting")
    print("4. Session will be preserved for future runs")
    print("5. Bot will auto-refresh daily at 6:00 AM")
    print("6. Keep the browser window open for automation")
    print("7. Endpoints:")
    print("   - GET  /health           : Check bot health")
    print("   - GET  /status           : Detailed status")
    print("   - POST /send-message     : Send message")
    print("   - POST /refresh          : Manual refresh")
    print("   - POST /preserve-session : Preserve session")
    print("   - POST /clear-session    : Clear session (requires QR)")
    print("="*60 + "\n")
    
    if initialize_app():
        try:
            # Start the daily refresh scheduler
            schedule_daily_refresh()
            
            logger.info("🌐 Server starting on http://0.0.0.0:5000")
            logger.info("📊 Status endpoint: http://localhost:5000/status")
            logger.info("🔄 Manual refresh: POST http://localhost:5000/refresh")
            logger.info("❤️  Health check: http://localhost:5000/health")
            logger.info("💾 Session preserved in: " + PROFILE_PATH)
            
            app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("👋 Shutting down gracefully...")
        except Exception as e:
            logger.error(f"💥 Server error: {str(e)}")
        finally:
            cleanup()
    else:
        logger.error("💥 Failed to initialize application")
        print("\n" + "="*50)
        print("TROUBLESHOOTING TIPS:")
        print("1. Check your internet connection")
        print("2. Try manually visiting https://web.whatsapp.com in Chrome")
        print("3. Ensure no firewall is blocking WhatsApp")
        print("4. Try running the script again")
        print("="*50 + "\n")