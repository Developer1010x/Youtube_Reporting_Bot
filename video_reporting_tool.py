
import os
import time
import random
import pandas as pd
import logging
import asyncio
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Constants
API_CREDENTIALS_DIR = "credentials"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# YouTube channels to monitor - store as a dictionary with labels
CHANNELS = {
    'Channel 1': 'https://www.youtube.com/channel/UC2UcOi6RPQG5J3DovCre1JA/videos',
    'Channel 2': 'https://www.youtube.com/channel/UCO4mttl54gQ0UW-DqyVrvLQ/videos'
    # Add more channels as needed
}

# Logging setup with file handler
def setup_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"youtube_bot_{time.strftime('%Y%m%d')}.log")
    
    logger = logging.getLogger("youtube_bot")
    logger.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    return logger

class YouTubeBot:
    def __init__(self, logger):
        self.logger = logger
        self.driver = None
        self.youtube = None
        self.is_authenticated = False
        self.current_credential = None
        self.status_callback = None
        self.report_reasons = {
            "S": "Sexual content",
            "V": "Violent or repulsive content",
            "H": "Hateful or abusive content",
            "P": "Harmful dangerous acts",
            "M": "Child abuse",
            "R": "Promotes terrorism",
            "C": "Spam or misleading"
        }
    
    def set_status_callback(self, callback):
        """Set a callback function to update UI status"""
        self.status_callback = callback
    
    def update_status(self, message):
        """Update status using callback if available"""
        if self.status_callback:
            self.status_callback(message)
        self.logger.info(message)
    
    def setup_driver(self):
        """Sets up an optimized Selenium WebDriver."""
        if self.driver:
            return
            
        self.update_status("Setting up WebDriver...")
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        options.add_argument("--window-size=1920,1080")
        
        # Add proxy if needed for avoiding rate limits
        # options.add_argument('--proxy-server=http://your-proxy-address:port')
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.update_status("WebDriver setup complete")
    
    def get_credential_files(self):
        """Returns a list of available credential files in the credentials directory."""
        if os.path.exists(API_CREDENTIALS_DIR):
            return [os.path.join(API_CREDENTIALS_DIR, f) for f in os.listdir(API_CREDENTIALS_DIR)
                    if f.endswith('.json')]
        return []
    
    def authenticate_youtube(self):
        """Authenticates with a randomly selected YouTube API credential."""
        try:
            credential_files = self.get_credential_files()
            if not credential_files:
                self.update_status("No API credential files found. Please add credentials first.")
                return False
                
            # Randomly select a credential file
            selected_credential = random.choice(credential_files)
            self.current_credential = os.path.basename(selected_credential)
            self.update_status(f"Authenticating with credential: {self.current_credential}")
            
            flow = InstalledAppFlow.from_client_secrets_file(selected_credential, SCOPES)
            credentials = flow.run_local_server(port=0)
            self.youtube = build("youtube", "v3", credentials=credentials)
            self.is_authenticated = True
            self.update_status("YouTube authentication successful!")
            return True
        except Exception as e:
            self.logger.error(f"YouTube authentication failed: {e}")
            messagebox.showerror("Error", f"YouTube authentication failed: {str(e)}")
            return False
    
    async def retrieve_video_links(self, random_channels=True):
        """Asynchronously scrapes video links from specified YouTube channels."""
        if not self.driver:
            self.setup_driver()
        
        video_data = []
        self.update_status("Retrieving video links...")
        
        try:
            # Get a copy of the channels dictionary
            channels_to_scrape = CHANNELS.copy()
            
            # If random channels is enabled and we have more than 1 channel,
            # select a random subset of 1-3 channels
            if random_channels and len(channels_to_scrape) > 1:
                num_channels = random.randint(1, min(3, len(channels_to_scrape)))
                channel_items = list(channels_to_scrape.items())
                random.shuffle(channel_items)
                channels_to_scrape = dict(channel_items[:num_channels])
                self.update_status(f"Randomly selected {num_channels} channels for scraping")
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                loop = asyncio.get_event_loop()
                tasks = []
                
                for channel_name, channel_url in channels_to_scrape.items():
                    tasks.append(
                        loop.run_in_executor(
                            executor,
                            self._scrape_channel,
                            channel_name,
                            channel_url,
                            video_data
                        )
                    )
                
                await asyncio.gather(*tasks)
            
            if video_data:
                df = pd.DataFrame(video_data, columns=["ChannelName", "VideoTitle", "VideoID", "PublishedDate"])
                
                # Save to CSV with timestamp to track different runs
                output_dir = "data"
                os.makedirs(output_dir, exist_ok=True)
                csv_path = os.path.join(output_dir, f"video_links_{time.strftime('%Y%m%d_%H%M%S')}.csv")
                df.to_csv(csv_path, index=False)
                
                self.update_status(f"Video links saved to {csv_path}")
                return df
            else:
                self.update_status("No videos found")
                return None
                
        except Exception as e:
            self.logger.error(f"Error retrieving video links: {e}")
            messagebox.showerror("Error", f"Failed to retrieve video links: {str(e)}")
            return None
    
    def _scrape_channel(self, channel_name, channel_url, video_data):
        """Scrapes a single channel for videos (used by ThreadPoolExecutor)"""
        try:
            self.driver.get(channel_url)
            self.update_status(f"Accessing {channel_name}...")
            
            # Wait for content to load with exponential backoff
            time.sleep(3)
            
            # Scroll down to load more videos
            for _ in range(3):
                self.driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
                time.sleep(1)
            
            videos = self.driver.find_elements(By.ID, "video-title")
            video_count = 0
            
            for video in videos:
                video_url = video.get_attribute("href")
                video_title = video.text
                published_date = "N/A"  # Could extract if available
                
                if video_url and "watch?v=" in video_url:
                    video_id = video_url.split("v=")[-1].split("&")[0]
                    video_data.append([channel_name, video_title, video_id, published_date])
                    video_count += 1
            
            self.update_status(f"Found {video_count} videos from {channel_name}")
            
        except Exception as e:
            self.logger.error(f"Error scraping {channel_name}: {e}")
    
    async def monitor_reports(self, csv_file=None, reason_id="S", report_limit=5, delay=2, random_selection=True, send_usage_data=True):
        """Reports videos with advanced rate limiting and retry logic."""
        if not self.is_authenticated:
            messagebox.showerror("Error", "YouTube API not authenticated.")
            return False
        
        if reason_id not in self.report_reasons:
            self.update_status(f"Invalid reason ID. Valid options are: {', '.join(self.report_reasons.keys())}")
            return False
            
        try:
            if csv_file:
                df = pd.read_csv(csv_file)
            else:
                # Use most recent CSV file in data directory
                data_dir = "data"
                csv_files = [f for f in os.listdir(data_dir) if f.startswith("video_links_") and f.endswith(".csv")]
                if not csv_files:
                    self.update_status("No video data files found. Please retrieve video links first.")
                    return False
                    
                # Sort by timestamp in filename
                csv_files.sort(reverse=True)
                csv_file = os.path.join(data_dir, csv_files[0])
                df = pd.read_csv(csv_file)
            
            self.update_status(f"Processing {len(df)} videos with {report_limit} report limit")
            
            # Create reports directory to store logs
            reports_dir = "reports"
            os.makedirs(reports_dir, exist_ok=True)
            report_log = os.path.join(reports_dir, f"report_log_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            
            report_results = []
            report_count = 0
            
            # If random selection, shuffle the dataframe
            if random_selection:
                df = df.sample(frac=1).reset_index(drop=True)
                self.update_status("Randomized video selection for reporting")
            
            # Get unique channel names for usage tracking
            channels_reported = set()
            
            # Process videos with exponential backoff for rate limiting
            for index, row in df.iterrows():
                if report_count >= report_limit:
                    self.update_status(f"Report limit of {report_limit} reached. Test complete.")
                    break
                
                video_id = row["VideoID"]
                video_title = row["VideoTitle"]
                channel_name = row["ChannelName"]
                channels_reported.add(channel_name)
                
                # Add random delay variations to seem more human-like
                random_delay = delay + (random.random() * 2 - 1)  # +/- 1 second variation
                
                # Exponential backoff retry logic
                max_retries = 3
                retry_count = 0
                backoff_time = random_delay
                
                while retry_count < max_retries:
                    try:
                        self.update_status(f"Testing report for '{video_title}' with reason '{self.report_reasons[reason_id]}'")
                        
                        # Make the API call to report
                        request = self.youtube.videos().reportAbuse(
                            body={
                                "videoId": video_id,
                                "reasonId": reason_id,
                                "secondaryReasonId": "",
                                "comments": "Testing YouTube reporting API for security evaluation"
                            }
                        )
                        response = request.execute()
                        
                        # If we get here, report was successful
                        report_time = time.strftime("%Y-%m-%d %H:%M:%S")
                        report_results.append({
                            "video_id": video_id,
                            "title": video_title,
                            "channel": channel_name,
                            "status": "success",
                            "reason": self.report_reasons[reason_id],
                            "timestamp": report_time
                        })
                        
                        report_count += 1
                        self.update_status(f"Report test {report_count}/{report_limit} completed")
                        
                        # Add random delay between successful reports to evade pattern detection
                        time.sleep(backoff_time + (0.5 * (report_count % 3)))
                        break
                        
                    except HttpError as e:
                        error_reason = str(e)
                        retry_count += 1
                        
                        if "quota" in error_reason.lower():
                            self.update_status("YouTube API quota exceeded. Test halted.")
                            report_results.append({
                                "video_id": video_id,
                                "title": video_title,
                                "channel": channel_name,
                                "status": "quota_exceeded",
                                "reason": self.report_reasons[reason_id],
                                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            # Save results before exiting
                            pd.DataFrame(report_results).to_csv(report_log, index=False)
                            return False
                            
                        elif retry_count < max_retries:
                            self.update_status(f"Retrying in {backoff_time}s ({retry_count}/{max_retries})...")
                            time.sleep(backoff_time)
                            backoff_time *= 2  # Exponential backoff
                        else:
                            self.update_status(f"Failed to report {video_id} after {max_retries} attempts")
                            report_results.append({
                                "video_id": video_id,
                                "title": video_title,
                                "channel": channel_name,
                                "status": "failed",
                                "error": error_reason,
                                "reason": self.report_reasons[reason_id],
                                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                            })
            
            # Save report results
            pd.DataFrame(report_results).to_csv(report_log, index=False)
            self.update_status(f"Testing complete. Results saved to {report_log}")
            
            # Send usage statistics if enabled
            if send_usage_data:
                usage_data = {
                    "session_id": int(time.time()),
                    "credential_used": self.current_credential,
                    "channels_reported": list(channels_reported),
                    "report_count": report_count,
                    "report_reason": self.report_reasons[reason_id],
                    "success_count": sum(1 for r in report_results if r["status"] == "success"),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self.send_usage_report(usage_data)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in report testing: {e}")
            messagebox.showerror("Error", f"Report testing failed: {str(e)}")
            return False
    
    def send_usage_report(self, report_data):
        """Send anonymous usage statistics to a central tracking server"""
        try:
            # This would be implemented with an API call to your tracking server
            # Example with requests (would need to be added to requirements):
            # import requests
            # response = requests.post("https://your-tracking-server.com/api/reports", json=report_data)
            # return response.status_code == 200
            
            # For now, just log that we would send data
            self.logger.info(f"Would send usage data: {report_data}")
            return True
        except Exception as e:
            self.logger.error(f"Error sending usage report: {e}")
            return False
    
    def close(self):
        """Cleanly closes resources."""
        if self.driver:
            self.update_status("Closing WebDriver...")
            self.driver.quit()
            self.driver = None

class YouTubeBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Reporting Tester")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.logger = setup_logging()
        self.bot = YouTubeBot(self.logger)
        self.bot.set_status_callback(self.update_status)
        
        # Create directory structure
        os.makedirs(API_CREDENTIALS_DIR, exist_ok=True)
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready - YouTube Bot Security Tester")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Tab 1: Setup
        setup_frame = ttk.Frame(notebook, padding=10)
        notebook.add(setup_frame, text="Setup")
        
        # API Credential management frame
        api_frame = ttk.LabelFrame(setup_frame, text="API Credentials", padding=10)
        api_frame.pack(fill=tk.X, pady=5)
        
        btn_add_api = ttk.Button(api_frame, text="Add API Credential", command=self.add_api_credential)
        btn_add_api.pack(side=tk.LEFT, padx=5)
        
        btn_view_apis = ttk.Button(api_frame, text="View Credentials", command=self.view_api_credentials)
        btn_view_apis.pack(side=tk.LEFT, padx=5)
        
        # Authentication frame
        auth_frame = ttk.LabelFrame(setup_frame, text="Authentication", padding=10)
        auth_frame.pack(fill=tk.X, pady=5)
        
        btn_authenticate = ttk.Button(auth_frame, text="Authenticate YouTube API", command=self.authenticate)
        btn_authenticate.pack(side=tk.LEFT, padx=5)
        
        # Tab 2: Data Collection
        collect_frame = ttk.Frame(notebook, padding=10)
        notebook.add(collect_frame, text="Data Collection")
        
        # Channel configuration
        channel_frame = ttk.LabelFrame(collect_frame, text="Monitored Channels", padding=10)
        channel_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.channels_text = tk.Text(channel_frame, height=8)
        self.channels_text.pack(fill=tk.BOTH, expand=True)
        self.update_channels_list()
        
        # Data collection settings
        settings_frame = ttk.LabelFrame(collect_frame, text="Collection Settings", padding=10)
        settings_frame.pack(fill=tk.X, pady=5)
        
        self.random_channels_var = tk.BooleanVar(value=True)
        random_channel_check = ttk.Checkbutton(
            settings_frame,
            text="Randomly Select Channels",
            variable=self.random_channels_var
        )
        random_channel_check.pack(anchor=tk.W, padx=5, pady=5)
        
        # Data collection buttons
        btn_frame = ttk.Frame(collect_frame, padding=5)
        btn_frame.pack(fill=tk.X, pady=5)
        
        btn_scrape = ttk.Button(btn_frame, text="Retrieve Video Links", command=self.start_scraping)
        btn_scrape.pack(side=tk.LEFT, padx=5)
        
        # Tab 3: Testing
        test_frame = ttk.Frame(notebook, padding=10)
        notebook.add(test_frame, text="Testing")
        
        # Test configuration
        config_frame = ttk.LabelFrame(test_frame, text="Test Configuration", padding=10)
        config_frame.pack(fill=tk.X, pady=5)
        
        # Report reason selection
        ttk.Label(config_frame, text="Report Reason:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.reason_var = tk.StringVar(value="S")
        reason_combo = ttk.Combobox(config_frame, textvariable=self.reason_var, width=30)
        reason_combo['values'] = [f"{k}: {v}" for k, v in self.bot.report_reasons.items()]
        reason_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        

        # Report limit
        ttk.Label(config_frame, text="Report Limit:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.limit_var = tk.StringVar(value="5")
        limit_entry = ttk.Entry(config_frame, textvariable=self.limit_var, width=10)
        limit_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Delay between reports
        ttk.Label(config_frame, text="Delay (seconds):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.delay_var = tk.StringVar(value="2")
        delay_entry = ttk.Entry(config_frame, textvariable=self.delay_var, width=10)
        delay_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Random selection option
        self.random_selection_var = tk.BooleanVar(value=True)
        random_check = ttk.Checkbutton(
            config_frame,
            text="Randomize Video Selection",
            variable=self.random_selection_var
        )
        random_check.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        # Usage data option
        self.usage_data_var = tk.BooleanVar(value=True)
        usage_check = ttk.Checkbutton(
            config_frame,
            text="Send Anonymous Usage Data",
            variable=self.usage_data_var
        )
        usage_check.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        # Data file selection
        file_frame = ttk.LabelFrame(test_frame, text="Data File", padding=10)
        file_frame.pack(fill=tk.X, pady=5)
        
        self.file_var = tk.StringVar()
        file_entry = ttk.Entry(file_frame, textvariable=self.file_var, width=50)
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        btn_browse = ttk.Button(file_frame, text="Browse", command=self.browse_file)
        btn_browse.pack(side=tk.LEFT, padx=5)
        
        # Start testing button
        btn_test = ttk.Button(test_frame, text="Start Test", command=self.start_testing)
        btn_test.pack(pady=10)
        
        # Log frame
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text['yscrollcommand'] = scrollbar.set
    
    def update_status(self, message):
        """Updates status bar and log"""
        self.status_var.set(message)
        
        # Add to log text
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        # Force update UI
        self.root.update_idletasks()
    
    def add_api_credential(self):
        """Prompts user to select an API credential file and copies it to credentials dir"""
        file_path = filedialog.askopenfilename(
            title="Select Google API Credential JSON File",
            filetypes=[("JSON Files", "*.json")]
        )
        
        if file_path:
            try:
                filename = os.path.basename(file_path)
                destination = os.path.join(API_CREDENTIALS_DIR, filename)
                
                # Copy file to credentials directory
                import shutil
                shutil.copyfile(file_path, destination)
                
                self.update_status(f"Added API credential: {filename}")
                messagebox.showinfo("Success", f"API credential added: {filename}")
            except Exception as e:
                self.logger.error(f"Error adding API credential: {e}")
                messagebox.showerror("Error", f"Failed to add API credential: {str(e)}")
    
    def view_api_credentials(self):
        """Shows a list of available API credentials"""
        credential_files = self.bot.get_credential_files()
        
        if not credential_files:
            messagebox.showinfo("API Credentials", "No API credentials found.")
            return
            
        # Extract just the filenames
        filenames = [os.path.basename(f) for f in credential_files]
        message = "Available API Credentials:\n\n" + "\n".join(filenames)
        
        messagebox.showinfo("API Credentials", message)
    
    def authenticate(self):
        """Authenticates with YouTube API"""
        if not self.bot.authenticate_youtube():
            self.update_status("YouTube authentication failed")
        else:
            self.update_status("YouTube authentication successful")
    
    def update_channels_list(self):
        """Updates the text widget with the list of monitored channels"""
        self.channels_text.config(state=tk.NORMAL)
        self.channels_text.delete(1.0, tk.END)
        
        for name, url in CHANNELS.items():
            self.channels_text.insert(tk.END, f"{name}: {url}\n")
            
        self.channels_text.config(state=tk.DISABLED)
    
    def start_scraping(self):
        """Starts the video link scraping process"""
        if not self.bot.driver:
            self.bot.setup_driver()
            
        async def scrape():
            random_channels = self.random_channels_var.get()
            await self.bot.retrieve_video_links(random_channels=random_channels)
            
        asyncio.run(scrape())
    
    def browse_file(self):
        """Browses for a CSV file of video links"""
        file_path = filedialog.askopenfilename(
            title="Select Video Links CSV File",
            filetypes=[("CSV Files", "*.csv")]
        )
        
        if file_path:
            self.file_var.set(file_path)
    
    def start_testing(self):
        """Starts the report testing process"""
        if not self.bot.is_authenticated:
            messagebox.showwarning("Warning", "Please authenticate with YouTube API first")
            return
            
        try:
            reason_id = self.reason_var.get().split(":")[0].strip()
            report_limit = int(self.limit_var.get())
            delay = float(self.delay_var.get())
            random_selection = self.random_selection_var.get()
            send_usage_data = self.usage_data_var.get()
            csv_file = self.file_var.get() if self.file_var.get() else None
            
            async def test():
                await self.bot.monitor_reports(
                    csv_file=csv_file,
                    reason_id=reason_id,
                    report_limit=report_limit,
                    delay=delay,
                    random_selection=random_selection,
                    send_usage_data=send_usage_data
                )
                
            asyncio.run(test())
            
        except ValueError as e:
            messagebox.showerror("Error", "Please enter valid numeric values for limit and delay")
    
    def on_closing(self):
        """Handle window closing event"""
        self.update_status("Shutting down...")
        if self.bot:
            self.bot.close()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = YouTubeBotApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
