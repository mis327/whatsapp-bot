from flask import Flask, request, jsonify
import threading
import time
import json
import logging
from datetime import datetime
import sys
import os
import traceback
from flask_cors import CORS  # Add CORS support

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ==================== INTEGRATE YOUR EXISTING CODE ====================
import pandas as pd
import urllib.parse
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import warnings
warnings.filterwarnings('ignore')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== YOUR CONFIGURATION ====================
class Config:
    # Safety limits
    MAX_MESSAGES_PER_DAY = 1000
    DELAY_BETWEEN_MESSAGES = 2.0  # Increased for stability
    DELAY_BETWEEN_BATCHES = 5
    BATCH_SIZE = 100
    RETRY_ATTEMPTS = 1
    
    # WhatsApp settings
    PROFILE_PATH = os.path.join(os.getcwd(), "whatsapp_profile")
    HEADLESS = False
    
    # Message settings
    MESSAGE_TEMPLATES = {
        "promotional": "Hello {name}, this is a promotional message from our company. Contact us for more details!",
        "notification": "Dear {name}, this is an important notification. Please check your account.",
        "greeting": "Hi {name}, hope you're having a great day! Just wanted to connect with you.",
        "followup": "Hello {name}, following up on our previous conversation. Let me know if you need any assistance.",
        "custom": ""
    }

# ==================== YOUR WHATSAPP DRIVER ====================
class WhatsAppDriver:
    def __init__(self):
        self.driver = None
        self.init_driver()
    
    def init_driver(self):
        options = Options()
        
        os.makedirs(Config.PROFILE_PATH, exist_ok=True)
        options.add_argument(f"--user-data-dir={Config.PROFILE_PATH}")
        options.add_argument("--profile-directory=Default")
        
        # Essential options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        
        if Config.HEADLESS:
            options.add_argument("--headless=new")
        
        # Stealth options
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option('useAutomationExtension', False)
        
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        prefs = {
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_settings.popups": 0,
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            self.driver = webdriver.Chrome(options=options)
            
            stealth_scripts = [
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined});',
                'Object.defineProperty(navigator, "plugins", {get: () => [1, 2, 3, 4, 5]});',
            ]
            
            for script in stealth_scripts:
                self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': script})
            
            logger.info("Chrome driver initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize driver: {str(e)}")
            raise
    
    def ensure_whatsapp_loaded(self):
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                if self.driver.current_url and "web.whatsapp.com" in self.driver.current_url:
                    try:
                        elements = self.driver.find_elements(By.XPATH, '//div[@contenteditable="true"][@data-tab]')
                        if elements:
                            logger.info("WhatsApp already loaded")
                            return True
                    except:
                        pass
                
                logger.info(f"Loading WhatsApp Web (attempt {attempt + 1}/{max_retries})...")
                self.driver.get("https://web.whatsapp.com")
                
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, '//body'))
                )
                
                time.sleep(3)
                
                if self.driver.find_elements(By.XPATH, '//div[@contenteditable="true"][@data-tab]'):
                    logger.info("WhatsApp loaded and logged in")
                    return True
                
                if self.driver.find_elements(By.XPATH, '//canvas[@aria-label="Scan me!"]') or \
                   self.driver.find_elements(By.XPATH, '//div[contains(text(), "QR")]'):
                    logger.info("Please scan QR code with your phone...")
                    
                    WebDriverWait(self.driver, 180).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab]'))
                    )
                    logger.info("QR code scanned successfully")
                    return True
                
                logger.info("WhatsApp loaded")
                return True
                    
            except TimeoutException:
                logger.error(f"WhatsApp loading timeout (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    time.sleep(3)
            except Exception as e:
                logger.error(f"Error loading WhatsApp: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(3)
        
        return False
    
    def send_message(self, phone_number, message):
        """Send a single message - FIXED PHONE NUMBER HANDLING"""
        try:
            # ============ FIX: Ensure phone_number is string ============
            phone_number = str(phone_number).strip()
            logger.debug(f"Processing phone number: {phone_number}")
            
            # Extract digits
            phone_digits = ''.join(filter(str.isdigit, phone_number))
            
            if not phone_digits:
                logger.error(f"No digits found in phone number: {phone_number}")
                return False
            
            # Format phone number
            if len(phone_digits) == 10:
                formatted_number = '+91' + phone_digits
            elif len(phone_digits) == 12 and phone_digits.startswith('91'):
                formatted_number = '+' + phone_digits
            elif len(phone_digits) == 11 and phone_digits.startswith('91'):
                formatted_number = '+91' + phone_digits[2:]
            else:
                formatted_number = '+' + phone_digits
            
            logger.debug(f"Formatted number: {formatted_number}")
            
            # URL encode the message
            encoded_message = urllib.parse.quote(message)
            
            # Create the direct WhatsApp URL
            url = f"https://web.whatsapp.com/send?phone={formatted_number}&text={encoded_message}"
            
            logger.debug(f"Opening URL for: {formatted_number}")
            
            # Navigate to the URL
            self.driver.get(url)
            
            # Wait for page to load
            time.sleep(3)  # Increased from 2 to 3 seconds
            
            # Check for invalid number
            invalid_indicators = [
                '//div[contains(text(), "Phone number shared via url is invalid.")]',
                '//div[contains(text(), "invalid phone number")]',
                '//div[contains(text(), "Couldn\'t find")]'
            ]
            
            for indicator in invalid_indicators:
                if len(self.driver.find_elements(By.XPATH, indicator)) > 0:
                    logger.warning(f"Invalid number: {formatted_number}")
                    return False
            
            # Find message input field
            try:
                text_box = None
                selectors = [
                    '//div[@contenteditable="true"][@data-tab="10"]',
                    '//div[@contenteditable="true"][@data-tab="9"]',
                    '//div[@contenteditable="true"][@role="textbox"]',
                    '//div[contains(@class, "selectable-text")][@contenteditable="true"]'
                ]
                
                for selector in selectors:
                    try:
                        elements = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_all_elements_located((By.XPATH, selector))
                        )
                        if elements:
                            text_box = elements[0]
                            break
                    except:
                        continue
                
                if not text_box:
                    logger.warning(f"Message input not found for {formatted_number}")
                    return False
                
                # WAIT for WhatsApp to auto-fill the message from URL
                time.sleep(2)  # Increased from 1.5 to 2 seconds
                
                # Check if message is already in the text box
                current_text = ""
                try:
                    current_text = text_box.text.strip()
                    if not current_text:
                        current_text = text_box.get_attribute("innerText").strip()
                except:
                    pass
                
                # If message is NOT already in the text box, type it
                if not current_text or message not in current_text:
                    # Clear the input first
                    text_box.click()
                    time.sleep(0.3)  # Increased from 0.2
                    
                    # Clear with JavaScript
                    self.driver.execute_script("""
                        var element = arguments[0];
                        element.focus();
                        element.innerHTML = '';
                        var event = new Event('input', { bubbles: true });
                        element.dispatchEvent(event);
                    """, text_box)
                    
                    time.sleep(0.5)
                    
                    # Type the message
                    chunks = [message[i:i+100] for i in range(0, len(message), 100)]
                    for chunk in chunks:
                        text_box.send_keys(chunk)
                        time.sleep(0.05)
                    
                    # Trigger input event
                    self.driver.execute_script("""
                        var element = arguments[0];
                        var event = new Event('input', { bubbles: true });
                        element.dispatchEvent(event);
                    """, text_box)
                    
                    time.sleep(0.5)
                else:
                    logger.debug(f"Message already in input for {formatted_number}")
                
                # Send message
                text_box.send_keys(Keys.ENTER)
                time.sleep(2)  # Increased from 1 to 2 seconds
                
                # Check if message was sent
                sent_checks = [
                    '//span[@data-icon="msg-dblcheck"]',
                    '//span[@data-icon="msg-check"]',
                    '//span[@data-icon="msg-time"]',
                    '//div[@aria-label="Message sent."]'
                ]
                
                for check in sent_checks:
                    if len(self.driver.find_elements(By.XPATH, check)) > 0:
                        logger.info(f"✓ Message sent to {formatted_number}")
                        return True
                
                # Additional check: look for sending status
                time.sleep(1)
                if len(self.driver.find_elements(By.XPATH, '//div[contains(@class, "message-out")]')) > 0:
                    logger.info(f"✓ Message sent to {formatted_number} (found in chat)")
                    return True
                
                logger.warning(f"Could not confirm message sent to {formatted_number}")
                return False
                
            except Exception as e:
                logger.error(f"Error in message input/send for {formatted_number}: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending to {phone_number}: {str(e)}")
            return False
    
    def close(self):
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Driver closed")
            except Exception as e:
                logger.error(f"Error closing driver: {e}")

# ==================== MODIFIED BULK SENDER ====================
class BulkSender:
    def __init__(self, whatsapp_driver, callback_url=None):
        self.whatsapp = whatsapp_driver
        self.callback_url = callback_url
        self.sent_count = 0
        self.failed_count = 0
        self.running = True
    
    def send_bulk(self, contacts, message_template, delay=2):
        """Send bulk messages with callback support"""
        total_contacts = len(contacts)
        
        logger.info(f"Starting bulk send: {total_contacts} contacts")
        
        # Ensure WhatsApp is loaded
        if not self.whatsapp.ensure_whatsapp_loaded():
            logger.error("WhatsApp not loaded properly")
            return False
        
        # Process all contacts
        for i, contact in enumerate(contacts):
            if not self.running:
                logger.info("Bulk sending stopped by user")
                break
            
            try:
                # Personalize message
                personalized_msg = self.personalize_message(message_template, contact)
                
                # Send message
                success = self.whatsapp.send_message(contact['phone'], personalized_msg)
                
                # Update counters
                if success:
                    self.sent_count += 1
                    logger.info(f"[{self.sent_count}/{total_contacts}] ✓ Sent to {contact.get('name', 'Unknown')} ({contact['phone']})")
                    
                    # Callback to update status in Google Sheets
                    if self.callback_url:
                        self.send_callback(contact['phone'], "Sent", personalized_msg[:100])
                else:
                    self.failed_count += 1
                    logger.error(f"[{i+1}/{total_contacts}] ✗ Failed: {contact['phone']}")
                    
                    # Callback for failed
                    if self.callback_url:
                        self.send_callback(contact['phone'], "Failed", "Failed to send")
                
                # Delay between messages
                if i < len(contacts) - 1:
                    time.sleep(max(1.0, delay + random.uniform(-0.3, 0.3)))
                    
            except Exception as e:
                logger.error(f"Error processing contact {contact.get('phone', 'Unknown')}: {str(e)}")
                self.failed_count += 1
        
        logger.info(f"Bulk send completed: {self.sent_count} sent, {self.failed_count} failed")
        return True
    
    def personalize_message(self, template, contact):
        """Personalize message with contact data - FIXED VERSION"""
        message = template
        
        # ============ FIX: Ensure all values are strings ============
        # Replace variables
        replacements = {
            "{name}": str(contact.get('name', '')),
            "{phone}": str(contact.get('phone', '')),
            "{index}": str(contact.get('index', '')),
            "{date}": datetime.now().strftime("%d/%m/%Y"),
            "{time}": datetime.now().strftime("%H:%M"),
            "{day}": datetime.now().strftime("%A")
        }
        
        for key, value in replacements.items():
            message = message.replace(key, value)
        
        # Add slight variations to avoid spam detection
        if random.random() < 0.3:
            greetings = {
                "Hello": ["Hi", "Hey", "Hello", "Greetings"],
                "Hi": ["Hello", "Hey", "Hi there"],
                "Dear": ["Hello", "Hi", "Dear"]
            }
            
            for original, variations in greetings.items():
                if original in message:
                    message = message.replace(original, random.choice(variations), 1)
                    break
        
        return message
    
    def send_callback(self, phone, status, message):
        """Send callback to Google Apps Script"""
        try:
            import requests
            callback_data = {
                'api_key': 'whatsapp-bot-2024',
                'action': 'update_status',
                'phone': str(phone),  # Ensure phone is string
                'status': status,
                'message': message
            }
            
            response = requests.post(
                self.callback_url,
                json=callback_data,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.debug(f"Callback sent for {phone}: {status}")
            else:
                logger.warning(f"Callback failed for {phone}: {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Could not send callback: {e}")

# ==================== FIXED FLASK WEBHOOK SERVER ====================
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global configuration - FIXED VERSION
CONFIG = {
    'api_key': 'whatsapp-bot-2024',
    'active_jobs': {},
    'whatsapp_driver': None,
    'bulk_sender': None,
    'apps_script_webhook': None
}

@app.route('/', methods=['GET'])
def index():
    """Root endpoint to verify server is running"""
    return jsonify({
        'success': True,
        'message': 'WhatsApp Bulk Sender API',
        'endpoints': {
            '/test': 'GET - Test connection',
            '/health': 'GET - Health check',
            '/start': 'POST - Start sending',
            '/stop': 'POST - Stop sending',
            '/status/<job_id>': 'GET - Get job status'
        },
        'timestamp': datetime.now().isoformat(),
        'version': '3.0'
    })

@app.route('/test', methods=['GET'])
def test_connection():
    """Test endpoint - FIXED to ensure proper JSON response"""
    try:
        logger.info("Test connection endpoint called")
        response_data = {
            'success': True,
            'message': 'WhatsApp Python bot is running and ready',
            'timestamp': datetime.now().isoformat(),
            'version': '3.0',
            'active_jobs': len(CONFIG['active_jobs']),
            'status': 'ready'
        }
        
        # Set proper headers
        response = jsonify(response_data)
        response.headers['Content-Type'] = 'application/json'
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        logger.info(f"Test response: {response_data}")
        return response
        
    except Exception as e:
        logger.error(f"Error in test endpoint: {str(e)}")
        error_response = jsonify({
            'success': False,
            'error': str(e)
        })
        error_response.headers['Content-Type'] = 'application/json'
        return error_response, 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_jobs': len(CONFIG['active_jobs']),
        'jobs': list(CONFIG['active_jobs'].keys())
    })

@app.route('/start', methods=['POST'])
def start_sending():
    """Start WhatsApp bulk sending from Google Apps Script"""
    try:
        logger.info("=" * 50)
        logger.info("START REQUEST RECEIVED")
        logger.info(f"Headers: {dict(request.headers)}")
        
        if not request.data:
            logger.error("No data received")
            return jsonify({'success': False, 'error': 'No data received'}), 400
        
        data = request.get_json()
        if not data:
            logger.error("Invalid JSON received")
            return jsonify({'success': False, 'error': 'Invalid JSON'}), 400
        
        logger.info(f"Received start request with job_id: {data.get('job_id')}")
        
        # Verify API key
        if data.get('api_key') != CONFIG['api_key']:
            logger.error(f"Invalid API key: {data.get('api_key')}")
            return jsonify({'success': False, 'error': 'Invalid API key'}), 401
        
        # Get data from request
        job_id = data.get('job_id')
        if not job_id:
            job_id = f'job_{int(time.time())}_{os.getpid()}'
        
        contacts = data.get('contacts', [])
        message_template = data.get('message', '')
        delay = data.get('delay', 2)
        max_messages = data.get('max_messages', 500)
        
        logger.info(f"Job {job_id}: Starting with {len(contacts)} contacts")
        
        # ============ FIX: Clean contact data ============
        cleaned_contacts = []
        for i, contact in enumerate(contacts):
            cleaned_contact = {
                'index': i + 1,
                'name': str(contact.get('name', f'Contact {i+1}')).strip(),
                'phone': str(contact.get('phone', '')).strip(),
                'status': str(contact.get('status', 'Pending')).strip(),
                'row': contact.get('row', i + 2)
            }
            cleaned_contacts.append(cleaned_contact)
        
        logger.info(f"First 3 cleaned contacts: {cleaned_contacts[:3]}")
        
        # Store callback URL if provided
        if 'callback_url' in data:
            CONFIG['apps_script_webhook'] = data['callback_url']
            logger.info(f"Callback URL set: {CONFIG['apps_script_webhook']}")
        
        # Initialize job entry BEFORE starting thread
        CONFIG['active_jobs'][job_id] = {
            'status': 'initializing',
            'started_at': datetime.now().isoformat(),
            'total_contacts': len(cleaned_contacts),
            'sent': 0,
            'failed': 0,
            'progress': 0
        }
        
        # Start sending in background thread
        thread = threading.Thread(
            target=run_whatsapp_bulk_send,
            args=(job_id, cleaned_contacts, message_template, delay, max_messages),
            daemon=True,
            name=f"WhatsAppJob-{job_id}"
        )
        thread.start()
        
        # Update job status
        CONFIG['active_jobs'][job_id]['status'] = 'running'
        CONFIG['active_jobs'][job_id]['thread'] = thread
        
        logger.info(f"Job {job_id}: Thread started successfully")
        
        response_data = {
            'success': True,
            'job_id': job_id,
            'message': 'WhatsApp bulk sending started successfully',
            'contacts_count': len(cleaned_contacts),
            'estimated_time': f"{(len(cleaned_contacts) * delay) / 60:.1f} minutes",
            'status_url': f"https://3713-106-219-147-26.ngrok-free.app/status/{job_id}"
        }
        
        response = jsonify(response_data)
        response.headers['Content-Type'] = 'application/json'
        response.headers['Access-Control-Allow-Origin'] = '*'
        
        return response
        
    except Exception as e:
        logger.error(f"Error starting job: {str(e)}")
        logger.error(traceback.format_exc())
        error_response = jsonify({'success': False, 'error': str(e)})
        error_response.headers['Content-Type'] = 'application/json'
        return error_response, 500

@app.route('/stop', methods=['POST'])
def stop_sending():
    """Stop all sending jobs"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400
        
        # Verify API key
        if data.get('api_key') != CONFIG['api_key']:
            return jsonify({'success': False, 'error': 'Invalid API key'}), 401
        
        stop_count = 0
        for job_id, job_info in CONFIG['active_jobs'].items():
            if job_info['status'] in ['running', 'processing']:
                CONFIG['active_jobs'][job_id]['status'] = 'stopping'
                stop_count += 1
        
        # Stop WhatsApp driver
        if CONFIG['bulk_sender']:
            try:
                CONFIG['bulk_sender'].running = False
            except:
                pass
        
        if CONFIG['whatsapp_driver']:
            try:
                CONFIG['whatsapp_driver'].close()
            except:
                pass
        
        logger.info(f"Stopped {stop_count} jobs")
        return jsonify({
            'success': True, 
            'message': f'Stopped {stop_count} jobs',
            'stopped_jobs': stop_count
        })
        
    except Exception as e:
        logger.error(f"Error stopping jobs: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Get status of a specific job"""
    try:
        logger.info(f"Status request for job: {job_id}")
        
        if job_id in CONFIG['active_jobs']:
            job = CONFIG['active_jobs'][job_id]
            response_data = {
                'success': True,
                'job_id': job_id,
                'status': job['status'],
                'started_at': job['started_at'],
                'total_contacts': job['total_contacts'],
                'sent': job.get('sent', 0),
                'failed': job.get('failed', 0),
                'progress': job.get('progress', 0)
            }
            
            # Add completion time if job is completed
            if 'completed_at' in job:
                response_data['completed_at'] = job['completed_at']
            
            response = jsonify(response_data)
            response.headers['Content-Type'] = 'application/json'
            response.headers['Access-Control-Allow-Origin'] = '*'
            
            return response
        else:
            error_response = jsonify({
                'success': False, 
                'error': f'Job {job_id} not found'
            })
            error_response.headers['Content-Type'] = 'application/json'
            return error_response, 404
            
    except Exception as e:
        logger.error(f"Error getting job status: {str(e)}")
        error_response = jsonify({'success': False, 'error': str(e)})
        error_response.headers['Content-Type'] = 'application/json'
        return error_response, 500

@app.route('/callback', methods=['POST'])
def callback():
    """Callback endpoint for status updates (optional)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400
            
        logger.info(f"Callback received: {data}")
        return jsonify({'success': True, 'message': 'Callback received'})
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def run_whatsapp_bulk_send(job_id, contacts, message_template, delay, max_messages):
    """Run the WhatsApp bulk sending in background thread - FIXED VERSION"""
    whatsapp = None
    try:
        # Check if job exists and update status
        if job_id not in CONFIG['active_jobs']:
            CONFIG['active_jobs'][job_id] = {
                'status': 'processing',
                'started_at': datetime.now().isoformat(),
                'total_contacts': len(contacts)
            }
        else:
            CONFIG['active_jobs'][job_id]['status'] = 'processing'
        
        logger.info(f"Job {job_id}: Processing {len(contacts)} contacts")
        
        # Limit contacts if needed
        if len(contacts) > max_messages:
            contacts = contacts[:max_messages]
            logger.info(f"Job {job_id}: Limited to {max_messages} contacts")
        
        # Initialize WhatsApp
        logger.info(f"Job {job_id}: Initializing WhatsApp driver...")
        whatsapp = WhatsAppDriver()
        CONFIG['whatsapp_driver'] = whatsapp
        
        # Update Config delay
        Config.DELAY_BETWEEN_MESSAGES = delay
        
        # Start sending
        logger.info(f"Job {job_id}: Initializing WhatsApp...")
        
        # Ensure WhatsApp is loaded
        if not whatsapp.ensure_whatsapp_loaded():
            raise Exception("Failed to load WhatsApp Web")
        
        logger.info(f"Job {job_id}: WhatsApp loaded, starting to send messages")
        
        sent_count = 0
        failed_count = 0
        
        for i, contact in enumerate(contacts):
            # Check if job was stopped
            if job_id in CONFIG['active_jobs'] and CONFIG['active_jobs'][job_id].get('status') == 'stopping':
                logger.info(f"Job {job_id}: Stopped by user")
                CONFIG['active_jobs'][job_id]['status'] = 'stopped'
                break
            
            try:
                # Personalize message
                personalized_msg = message_template.replace('{name}', str(contact.get('name', '')))
                personalized_msg = personalized_msg.replace('{phone}', str(contact.get('phone', '')))
                personalized_msg = personalized_msg.replace('{date}', datetime.now().strftime("%d/%m/%Y"))
                personalized_msg = personalized_msg.replace('{time}', datetime.now().strftime("%H:%M"))
                
                logger.info(f"Job {job_id}: [{i+1}/{len(contacts)}] Sending to {contact.get('name', 'Unknown')} ({contact['phone']})")
                
                # Send message
                success = whatsapp.send_message(contact['phone'], personalized_msg)
                
                # Update counters
                if success:
                    sent_count += 1
                    logger.info(f"Job {job_id}: [{i+1}/{len(contacts)}] ✓ Sent to {contact.get('name', 'Unknown')}")
                    
                    # Send callback for successful send
                    if CONFIG['apps_script_webhook']:
                        send_callback(contact['phone'], 'Sent', personalized_msg[:50], job_id)
                else:
                    failed_count += 1
                    logger.error(f"Job {job_id}: [{i+1}/{len(contacts)}] ✗ Failed: {contact['phone']}")
                    
                    # Send callback for failed send
                    if CONFIG['apps_script_webhook']:
                        send_callback(contact['phone'], 'Failed', "Failed to send message", job_id)
                
                # Update progress in active jobs
                if job_id in CONFIG['active_jobs']:
                    CONFIG['active_jobs'][job_id]['sent'] = sent_count
                    CONFIG['active_jobs'][job_id]['failed'] = failed_count
                    CONFIG['active_jobs'][job_id]['progress'] = int(((i + 1) / len(contacts)) * 100)
                
                # Delay between messages
                if i < len(contacts) - 1:
                    time.sleep(max(2.0, delay))  # Minimum 2 seconds delay
                    
            except Exception as e:
                logger.error(f"Job {job_id}: Error sending to {contact.get('phone', 'Unknown')}: {str(e)}")
                logger.error(traceback.format_exc())
                failed_count += 1
                
                # Send error callback
                if CONFIG['apps_script_webhook']:
                    send_callback(contact['phone'], 'Failed', f"Error: {str(e)[:50]}", job_id)
                
                if job_id in CONFIG['active_jobs']:
                    CONFIG['active_jobs'][job_id]['failed'] = failed_count
        
        # Update final status
        if job_id in CONFIG['active_jobs']:
            if CONFIG['active_jobs'][job_id].get('status') != 'stopped':
                CONFIG['active_jobs'][job_id]['status'] = 'completed'
            CONFIG['active_jobs'][job_id]['sent'] = sent_count
            CONFIG['active_jobs'][job_id]['failed'] = failed_count
            CONFIG['active_jobs'][job_id]['completed_at'] = datetime.now().isoformat()
            CONFIG['active_jobs'][job_id]['progress'] = 100
        
        logger.info(f"Job {job_id}: ✅ Completed - {sent_count} sent, {failed_count} failed")
        
        # Send final callback
        send_final_callback(job_id, sent_count, failed_count)
        
    except Exception as e:
        logger.error(f"Job {job_id}: ❌ Error in bulk send: {str(e)}")
        logger.error(traceback.format_exc())
        
        if job_id in CONFIG['active_jobs']:
            CONFIG['active_jobs'][job_id]['status'] = 'failed'
            CONFIG['active_jobs'][job_id]['error'] = str(e)
        
        # Send error callback
        send_error_callback(job_id, str(e))
        
    finally:
        # Cleanup
        if whatsapp:
            try:
                whatsapp.close()
                logger.info(f"Job {job_id}: WhatsApp driver closed")
            except Exception as e:
                logger.error(f"Job {job_id}: Error closing driver: {e}")

def send_callback(phone, status, message, job_id):
    """Send callback to Google Apps Script"""
    try:
        if not CONFIG['apps_script_webhook']:
            logger.warning(f"No callback URL configured for job {job_id}")
            return
        
        import requests
        callback_data = {
            'api_key': CONFIG['api_key'],
            'action': 'update_status',
            'phone': str(phone),  # Ensure phone is string
            'status': status,
            'message': message,
            'job_id': job_id
        }
        
        logger.info(f"Sending callback for {phone}: {status}")
        
        response = requests.post(
            CONFIG['apps_script_webhook'],
            json=callback_data,
            timeout=5
        )
        
        if response.status_code == 200:
            logger.debug(f"Callback sent for {phone}: {status}")
        else:
            logger.warning(f"Callback failed for {phone}: {response.status_code}")
            
    except Exception as e:
        logger.warning(f"Could not send callback: {e}")

def send_final_callback(job_id, sent_count, failed_count):
    """Send final callback to Google Apps Script"""
    try:
        if not CONFIG['apps_script_webhook']:
            logger.warning(f"No callback URL configured for job {job_id}")
            return
        
        # Try to create completed URL from callback URL
        if 'action=update_status' in CONFIG['apps_script_webhook']:
            completed_url = CONFIG['apps_script_webhook'].replace('action=update_status', 'action=job_completed')
        else:
            completed_url = CONFIG['apps_script_webhook'] + '?action=job_completed'
        
        import requests
        callback_data = {
            'api_key': CONFIG['api_key'],
            'action': 'job_completed',
            'job_id': job_id,
            'sent': sent_count,
            'failed': failed_count,
            'total': sent_count + failed_count
        }
        
        logger.info(f"Sending final callback for job {job_id}")
        
        response = requests.post(
            completed_url,
            json=callback_data,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Final callback sent for job {job_id}")
        else:
            logger.warning(f"Final callback failed: {response.status_code}")
            
    except Exception as e:
        logger.warning(f"Could not send final callback: {e}")

def send_error_callback(job_id, error_message):
    """Send error callback to Google Apps Script"""
    try:
        if not CONFIG['apps_script_webhook']:
            logger.warning(f"No callback URL configured for job {job_id}")
            return
        
        # Try to create error URL from callback URL
        if 'action=update_status' in CONFIG['apps_script_webhook']:
            error_url = CONFIG['apps_script_webhook'].replace('action=update_status', 'action=job_error')
        else:
            error_url = CONFIG['apps_script_webhook'] + '?action=job_error'
        
        import requests
        callback_data = {
            'api_key': CONFIG['api_key'],
            'action': 'job_error',
            'job_id': job_id,
            'error': error_message[:500]  # Limit error message length
        }
        
        logger.info(f"Sending error callback for job {job_id}")
        
        response = requests.post(
            error_url,
            json=callback_data,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Error callback sent for job {job_id}")
        else:
            logger.warning(f"Error callback failed: {response.status_code}")
            
    except Exception as e:
        logger.warning(f"Could not send error callback: {e}")

if __name__ == '__main__':
    print("=" * 70)
    print("WHATSAPP BULK SENDER WEBHOOK SERVER - FIXED CONNECTION VERSION")
    print("=" * 70)
    print(f"✓ API Key: {CONFIG['api_key']}")
    print(f"✓ Port: 5000")
    print(f"✓ Ngrok URL: https://3713-106-219-147-26.ngrok-free.app")
    print(f"✓ CORS Enabled")
    print(f"✓ Fixes applied:")
    print(f"  - Added CORS support")
    print(f"  - Improved error handling")
    print(f"  - Better JSON response formatting")
    print(f"  - Enhanced logging")
    print("=" * 70)
    print(f"📋 Available endpoints:")
    print(f"  GET  /        - API information")
    print(f"  GET  /test    - Test connection")
    print(f"  GET  /health  - Health check")
    print(f"  POST /start   - Start sending")
    print(f"  POST /stop    - Stop sending")
    print(f"  GET  /status/<job_id> - Job status")
    print("=" * 70)
    
    # Run the server
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        input("Press Enter to exit...")