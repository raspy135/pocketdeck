# main.py - Google Drive OAuth Device Flow for ESP32
import urequests
import ujson
import time
import network
import googleapi_posts
from machine import Pin
import gc

# Wi-Fi Configuration
WIFI_SSID = "your_wifi"
WIFI_PASS = "your_password"

# Google OAuth Configuration (from your Google Cloud Console)
CLIENT_ID = "410521312052-b7im4ugrl7ifjdb9dcpe5v4tk391uq3s.apps.googleusercontent.com"
SCOPES = "https://www.googleapis.com/auth/drive.file"  # Limited scope

# Endpoints
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Storage for tokens
TOKEN_FILE = "/config/tokens.json"

vs = None

def print_vs(str,end='\n'):
  print(str, file=vs, end=end)

def get_device_code():
    """Step 1: Get device code and user verification URL"""
    print_vs("Requesting device code...")
    
    payload = {
        "client_id": CLIENT_ID,
        "scope": SCOPES
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = urequests.post(DEVICE_CODE_URL, json=payload, headers=headers)
        data = response.json()
        response.close()
        
        if "device_code" in data:
            print_vs("\n" + "="*40)
            print_vs(f"Go to:{data["verification_url"]}")
            print_vs(f"Enter code:{data["user_code"]}")
            print_vs("="*40 + "\n")
            
            return {
                "device_code": data["device_code"],
                "user_code": data["user_code"],
                "verification_url": data["verification_url"],
                "interval": data.get("interval", 5),  # Polling interval
                "expires_in": data.get("expires_in", 1800)  # 30 minutes
            }
        else:
            print_vs("Error getting device code:", data)
            return None
            
    except Exception as e:
        print_vs(f"Request failed:{e}")
        return None

def poll_for_tokens(device_code, interval=5, timeout=120):
    """Step 2: Poll for access token"""
    print_vs("Waiting for authorization...")
    print_vs("(User needs to enter the code on Google's site)")
    
    payload = {
        "client_id": CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }
    
    start_time = time.time()

 
    while time.time() - start_time < timeout:
        try:
            response = googleapi_posts.post(TOKEN_URL, json=payload)
            data = response.json()
            response.close()
            
            if "access_token" in data:
                print_vs("Authorization successful!")
                return data  # Contains access_token, refresh_token, expires_in
            elif "error" in data:
                if data["error"] == "authorization_pending":
                    print_vs(".",end='')
                elif data["error"] == "slow_down":
                    interval += 5  # Google says to slow down
                else:
                    print_vs("Error:", data["error"])
                    break
        
        except Exception as e:
            print_vs(f"Poll error:{e}")
        
        time.sleep(interval)
    
    print_vs("\n❌ Authorization timed out or failed")
    return None

def save_tokens(tokens):
    """Save tokens to file"""
    try:
        with open(TOKEN_FILE, "w") as f:
            ujson.dump(tokens, f)
        print_vs("Tokens saved")
        return True
    except Exception as e:
        print_vs("Failed to save tokens:", e)
        return False

def load_tokens():
    """Load tokens from file"""
    try:
        with open(TOKEN_FILE, "r") as f:
            return ujson.load(f)
    except:
        return None

def refresh_access_token(refresh_token):
    """Refresh expired access token"""
    print_vs("Refreshing access token...")
    
    payload = {
        "client_id": CLIENT_ID,
        #"client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    try:
        response = googleapi_posts.post(TOKEN_URL, json=payload)
        data = response.json()
        response.close()
        
        if "access_token" in data:
            # Update stored tokens
            tokens = load_tokens() or {}
            tokens["access_token"] = data["access_token"]
            tokens["expires_in"] = data.get("expires_in", 3600)
            tokens["token_type"] = data.get("token_type", "Bearer")
            save_tokens(tokens)
            
            print_vs("Token refreshed")
            return data["access_token"]
        else:
            print_vs("Refresh failed:", data)
            return None
            
    except Exception as e:
        print_vs("Refresh error:", e)
        return None

def upload_file_to_drive(file_path, drive_filename=None):
    """Upload a file to Google Drive"""
    tokens = load_tokens()
    
    if not tokens or "access_token" not in tokens:
        print_vs("No valid tokens. Need to authenticate first.")
        return False
    
    # Check if token needs refresh
    if tokens.get("expires_at", 0) < time.time():
        print_vs("Token expired, refreshing...")
        new_token = refresh_access_token(tokens.get("refresh_token"))
        if not new_token:
            return False
        access_token = new_token
    else:
        access_token = tokens["access_token"]
    
    # Prepare file
    if not drive_filename:
        drive_filename = file_path.split("/")[-1]
    
    try:
        with open(file_path, "rb") as f:
            file_content = f.read()
    except Exception as e:
        print_vs("Failed to read file:", e)
        return False
    
    # Create metadata
    metadata = {
        "name": drive_filename,
        "mimeType": "application/octet-stream"
    }
    
    # Upload file
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8"
    }
    
    # Create file metadata first
    try:
        # Method 1: Simple upload (for small files < 5MB)
        url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=media"
        
        # First set metadata
        meta_response = urequests.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=metadata
        )
        
        if meta_response.status_code == 200:
            file_data = meta_response.json()
            file_id = file_data["id"]
            meta_response.close()
            
            # Now upload content
            upload_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream"
            }
            
            upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            upload_response = urequests.patch(upload_url, headers=upload_headers, data=file_content)
            
            if upload_response.status_code in [200, 201]:
                print_vs(f"File uploaded: {drive_filename}")
                upload_response.close()
                return True
            else:
                print_vs("Upload failed:", upload_response.text)
                upload_response.close()
                return False
        else:
            print_vs("Metadata creation failed:", meta_response.text)
            meta_response.close()
            return False
            
    except Exception as e:
        print_vs("Upload error:", e)
        return False

def list_drive_files():
    """List files in Google Drive"""
    tokens = load_tokens()
    
    if not tokens or "access_token" not in tokens:
        return []
    
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    
    try:
        response = urequests.get(
            "https://www.googleapis.com/drive/v3/files?pageSize=10",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            response.close()
            
            files = []
            for item in data.get("files", []):
                files.append(f"{item['name']} ({item['id']})")
            return files
        else:
            print_vs("List failed:", response.text)
            response.close()
            return []
            
    except Exception as e:
        print_vs("List error:", e)
        return []

def oauth_setup():
    """Complete OAuth setup flow"""
    print_vs("\n" + "="*40)
    print_vs("Google Drive OAuth Setup")
    print_vs("="*40)
    
    # Check if already authenticated
    tokens = load_tokens()
    if tokens and "access_token" in tokens:
        print_vs("Already authenticated!")
        return True
    
    # Get device code
    device_data = get_device_code()
    if not device_data:
        return False
    
    # Poll for authorization
    tokens = poll_for_tokens(
        device_data["device_code"],
        device_data["interval"],
        device_data["expires_in"]
    )
    
    if tokens:
        # Calculate expiration timestamp
        tokens["expires_at"] = time.time() + tokens["expires_in"]
        save_tokens(tokens)
        return True
    else:
        return False

def main(vs_arg, args):
    global vs
    vs = vs_arg
    """Main program"""
    print_vs("ESP32 Google Drive Sync")
    
    isFirst = True
    # Main menu
    while isFirst:
        isFirst = False
        print_vs("\n" + "="*40)
        print_vs("1. Setup Google Drive OAuth")
        print_vs("2. Upload test file")
        print_vs("3. List Drive files")
        print_vs("4. Exit")
        print_vs("="*40)
        
        # In real implementation, get input from buttons/screen
        # For now, simulate choice
        choice = "1"  # Change this based on your input method
        
        if choice == "1":
            if oauth_setup():
                print_vs("Setup complete!")
            else:
                print_vs("Setup failed")
                
        elif choice == "2":
            # Create a test file
            test_content = "Hello from ESP32 at " + str(time.time())
            with open("/test.txt", "w") as f:
                f.write(test_content)
            
            if upload_file_to_drive("/test.txt", "esp32_test.txt"):
                print_vs("Upload successful!")
            else:
                print_vs("Upload failed")
                
        elif choice == "3":
            files = list_drive_files()
            if files:
                print_vs("Files in Drive:")
                for f in files:
                    print_vs(f"  -{f}")
            else:
                print_vs("No files or failed to list")
                
        elif choice == "4":
            break
        
        time.sleep(2)


