import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from PIL import Image, ImageTk
import pandas as pd
from instagrapi import Client
import datetime
import os
import time
import random
import json
import threading
import requests
from ttkbootstrap import Style
from plyer import notification
from moviepy.editor import *
import moviepy.video.fx.all as transfx

client = Client()
current_dir = os.path.dirname(os.path.abspath(__file__))

# ----------------------------
# Configuration
# ----------------------------
CONFIG_PATH = os.path.join(current_dir, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(current_dir, "config.example.json")

if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(
        "config.json not found. Copy config.example.json to config.json and update the values."
    )

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

app_cfg = config.get("app", {})
instagram_cfg = config.get("instagram", {})
linkedin_cfg = config.get("linkedin", {})
paths_cfg = config.get("paths", {})
templates_cfg = config.get("templates", {})

DATA_FILE = os.path.join(current_dir, app_cfg.get("dataFile", "autopost.xlsx"))
TAGS_FILE = os.path.join(current_dir, app_cfg.get("tagsFile", "tags.txt"))
OUTPUT_IMAGES_DIR = os.path.join(current_dir, paths_cfg.get("outputImagesDir", "images"))
OUTPUT_VIDEOS_DIR = os.path.join(current_dir, paths_cfg.get("outputVideosDir", "videos"))


file_path = DATA_FILE

df = pd.read_excel(file_path)

if 'Posted' not in df.columns:
    df['Posted'] = False

uploaded_image_paths = [""]
template_images = {}
global logged_in
logged_in = False


def is_logged_in():
    global logged_in
    if logged_in:
        return True
    else:
        return False

def linkedin(caption, media_paths):
    """Publish to LinkedIn using the official LinkedIn API (UGC Posts).

    Notes:
    - Requires a valid access token and appropriate permissions enabled in your LinkedIn developer app.
    - Supports text-only posts and image posts. Video posting is not implemented in this public version.
    - All credentials/tokens must be provided via config.json (never commit secrets).
    """
    linkedin_cfg = config.get("linkedin", {})
    if not linkedin_cfg.get("enabled", False):
        update_status("LinkedIn posting is disabled in config.", notify=False)
        return True

    access_token = linkedin_cfg.get("accessToken", "").strip()
    author_urn = linkedin_cfg.get("authorUrn", "").strip()

    if not access_token or not author_urn:
        raise ValueError("LinkedIn config is missing accessToken and/or authorUrn.")

    # If any mp4 is provided, fail fast (public-safe simplification).
    for p in media_paths:
        if str(p).lower().endswith(".mp4"):
            raise NotImplementedError("LinkedIn video posting is not implemented in this public version.")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # Helper: register + upload a single image, return asset URN
    def upload_image(image_path: str) -> str:
        register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": author_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }
                ]
            }
        }
        r = requests.post(register_url, headers={**headers, "Content-Type": "application/json"}, json=register_payload, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"LinkedIn registerUpload failed ({r.status_code}): {r.text}")

        data = r.json()
        upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset = data["value"]["asset"]

        with open(image_path, "rb") as f:
            img_bytes = f.read()

        up = requests.put(upload_url, headers={**headers, "Content-Type": "application/octet-stream"}, data=img_bytes, timeout=60)
        if up.status_code >= 300:
            raise RuntimeError(f"LinkedIn upload failed ({up.status_code}): {up.text}")

        return asset

    # Prepare media list (images only)
    image_assets = []
    if media_paths:
        for p in media_paths[:9]:  # LinkedIn feed supports limited number of images
            image_assets.append(upload_image(p))

    # Create post
    ugc_url = "https://api.linkedin.com/v2/ugcPosts"
    if image_assets:
        share_content = {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": "IMAGE",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": ""},
                    "media": asset,
                    "title": {"text": ""}
                }
                for asset in image_assets
            ]
        }
    else:
        share_content = {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": "NONE"
        }

    payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }

    resp = requests.post(ugc_url, headers={**headers, "Content-Type": "application/json"}, json=payload, timeout=30)
    if resp.status_code >= 300:
        raise RuntimeError(f"LinkedIn post failed ({resp.status_code}): {resp.text}")

    return True


def make_video():
    intro_file = filedialog.askopenfilename(title="Select Intro Video", filetypes=[("Video Files", "*.mp4")])
    main_video_file = filedialog.askopenfilename(title="Select Main Video", filetypes=[("Video Files", "*.mp4")])
    outro_file = filedialog.askopenfilename(title="Select Outro Video", filetypes=[("Video Files", "*.mp4")])

    if intro_file and main_video_file and outro_file:
        intro = VideoFileClip(intro_file)
        main_video = VideoFileClip(main_video_file)
        outro = VideoFileClip(outro_file)

        slide_duration = 1

        intro_slide_out = intro.fx(transfx.fadeout, slide_duration)
        main_video_slide_in = main_video.set_start(intro.duration - slide_duration).fx(transfx.fadein, slide_duration)

        final_video = concatenate_videoclips([intro_slide_out, main_video_slide_in, outro], method="compose")
        
        output_dir = OUTPUT_VIDEOS_DIR
        os.makedirs(output_dir, exist_ok=True)
        
        unique_videoname = generate_unique_videoname(os.path.join(output_dir, "video.mp4"))
        final_video.write_videofile(unique_videoname, fps=60)

        update_status("Video created successfully!", notify=True)
    else:
        messagebox.showwarning("Input Error", "Please select all required video files.")
        

def move_up():
    selected_index = listbox.curselection()
    if selected_index:
        index = selected_index[0]
        if index > 0:
            item = listbox.get(index)
            listbox.delete(index)
            listbox.insert(index - 1, item)
            listbox.select_set(index - 1)
            uploaded_image_paths[index], uploaded_image_paths[index - 1] = uploaded_image_paths[index - 1], uploaded_image_paths[index]

def move_down():
    selected_index = listbox.curselection()
    if selected_index:
        index = selected_index[0]
        if index < listbox.size() - 1:
            item = listbox.get(index)
            listbox.delete(index)
            listbox.insert(index + 1, item)
            listbox.select_set(index + 1) 
            uploaded_image_paths[index], uploaded_image_paths[index + 1] = uploaded_image_paths[index + 1], uploaded_image_paths[index]


def update_listbox(image_paths):
    listbox.delete(0, tk.END)
    for path in image_paths:
        filename = os.path.basename(path)
        listbox.insert(tk.END, filename)
    
def upload_images():
    global uploaded_image_paths
    uploaded_image_paths=list(filedialog.askopenfilenames(
        title="Select Files",
        filetypes=[("Image Files", "*.png;*.jpg;*.jpeg"), ("Video Files", "*.mp4")]
    ))
    video_count = sum(1 for path in uploaded_image_paths if path.endswith('.mp4'))
    uploaded_image_paths = [path.replace('/', '\\') for path in uploaded_image_paths]
    if len(uploaded_image_paths) > 20:
        messagebox.showwarning("Error", "Maximum 20 images are allowed.")
    elif video_count > 1:
        messagebox.showwarning("Error", "Only one video file is allowed.")    
    elif uploaded_image_paths:
        update_listbox(uploaded_image_paths)
        print(uploaded_image_paths)
        update_status(f"{len(uploaded_image_paths)} images uploaded successfully!")        


def overlay_image(selected_template, image_path):
    template_path = template_paths[selected_template]
    transparent_image_path = os.path.join(current_dir, "transparent.png")
    try:
        template = Image.open(template_path).convert("RGBA")
        uploaded_image = Image.open(image_path).convert("RGBA")
        transparent_image = Image.open(transparent_image_path).convert("RGBA")

        if selected_template == "Template1":
            uploaded_image = uploaded_image.resize((995, 590))
            x, y = 40, 295
        elif selected_template == "Template2":
            uploaded_image = uploaded_image.resize((940, 627))
            x, y = 70, 227

        combined = Image.new("RGBA", template.size)
        combined.paste(template, (0, 0))
        combined.paste(uploaded_image, (x, y), uploaded_image)
        combined.paste(transparent_image, (0, 740), transparent_image)

        output_dir = OUTPUT_IMAGES_DIR
        os.makedirs(output_dir, exist_ok=True)
        combined_rgb = combined.convert("RGB")

        output_path = generate_unique_filename(os.path.join(output_dir, "combined_image.jpg"))
        combined_rgb.save(output_path, "JPEG")
        return output_path
    except Exception as e:
        messagebox.showerror("Error", str(e))
        return None


def generate_unique_filename(base_path):
    counter = 1
    while True:
        unique_path = f"{base_path[:-4]}{counter}.jpg"
        if not os.path.exists(unique_path):
            return unique_path
        counter += 1
def generate_unique_videoname(base_path):
    counter = 1
    while True:
        unique_path = f"{base_path[:-4]}{counter}.mp4"
        if not os.path.exists(unique_path):
            return unique_path
        counter += 1 

def share_now():
    def perform_share():
        if not is_logged_in():
            update_status("User is not logged in. Post was not shared.")
            return
        selected_template = template_var.get()
        combined_images = []

        if uploaded_image_paths:
            if listbox.size() == 1:
                image_path = [uploaded_image_paths[listbox.index(0)]]
                if image_path[0].endswith('.mp4'):
                    caption = caption_entry.get("1.0", tk.END).strip()
                    if caption:
                        try:
                            success = linkedin(caption, image_path)
                            if success:
                                success = client.clip_upload(image_path[0], caption)
                                if success:
                                    update_status("Reels posted successfully!")
                                else:
                                    update_status("Instagram post failed!")
                            else:
                                update_status("LinkedIn post failed!")
                        except Exception as e:
                            messagebox.showerror("Upload Error", str(e))
                    else:
                        messagebox.showwarning("Input Error", "Please enter a caption.")
                else:
                    combined_image = overlay_image(selected_template, image_path[0])

                    if combined_image:
                        combined_images.append(combined_image)
                        caption = caption_entry.get("1.0", tk.END).strip()
                        if caption:
                            try:
                                success = linkedin(caption, combined_images)
                                if success:
                                    success = client.photo_upload(combined_images[0], caption)
                                    if success:
                                        update_status("Photo posted successfully!")
                                    else:
                                        update_status("Instagram post failed!")
                                else:
                                    update_status("LinkedIn post failed!")
                                combined_images.clear() 
                            except Exception as e:
                                messagebox.showerror("Upload Error", str(e))
                        else:
                            messagebox.showwarning("Input Error", "Please enter a caption.")
                    else:
                        messagebox.showwarning("Error", "An error occurred while applying the overlay.")
            else:
                sorted_image_paths = [uploaded_image_paths[listbox.index(i)] for i in range(listbox.size())]

                for index, image_path in enumerate(sorted_image_paths):
                    combined_image = overlay_image(selected_template, image_path)

                    if combined_image:
                        combined_images.append(combined_image)
                    else:
                        messagebox.showwarning("Error", f"Failed to apply overlay for photo {index + 1}.")
                        return

                caption = caption_entry.get("1.0", tk.END).strip()
                if caption:
                    try:
                        success = linkedin(caption, combined_images)
                        if success:
                            success = client.album_upload(combined_images, caption)
                            if success:
                                update_status("Album posted successfully!")
                            else:
                                update_status("Instagram post failed!")                            
                        else:                    
                            update_status("LinkedIn post failed!")
                        combined_images.clear() 
                    except Exception as e:
                        messagebox.showerror("Upload Error", str(e))
                else:
                    messagebox.showwarning("Input Error", "Please enter a caption.")
        else:
            messagebox.showwarning("Input Error", "Please upload photos first.")

    # Bu işlemi arka planda çalıştırmak için bir iş parçacığı başlatıyoruz
    threading.Thread(target=perform_share, daemon=True).start()
    # combined_images.clear()  
    # listbox.delete(0, tk.END)



def schedule_post():
    date = date_entry.get()
    time = time_entry.get()
    caption = caption_entry.get("1.0", tk.END).strip()
    selected_template = template_var.get()

    if date and time and caption and uploaded_image_paths:
        date_time_str = f"{date} {time}"

        try:
            datetime.datetime.strptime(date_time_str, '%Y-%m-%d %H:%M')
            combined_images = []
            sorted_image_paths = [uploaded_image_paths[listbox.index(i)] for i in range(listbox.size())]

            for image_path in sorted_image_paths:
                if image_path.endswith('.mp4'):
                    new_row = pd.DataFrame({
                        'Date and Time': [date_time_str],
                        'Caption': [caption],
                        'Directory': [image_path],  # Join only MP4 file paths
                        'Posted': [False]
                    })
                else:
                    combined_image = overlay_image(selected_template, image_path)
                    if combined_image:
                        combined_images.append(combined_image)
                    else:
                        messagebox.showwarning("Error", f"An error occurred while overlaying for {image_path}.")
                        return

            if combined_images:
                new_row = pd.DataFrame({
                    'Date and Time': [date_time_str],
                    'Caption': [caption],
                    'Directory': [','.join(combined_images)],
                    'Posted': [False]
                })

            global df
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_excel(file_path, index=False)
            update_status("Post scheduled successfully!")
            #refresh_planned_posts()
        except ValueError:
            messagebox.showwarning("Input Error", "Please enter a valid date and time format.")
    else:
        messagebox.showwarning("Input Error", "Please fill in all fields.")

def update_status(message, notify=False):
    max_length = 150
    
    message = message.replace("\n", " ").strip()
    
    if len(message) > max_length:
        message = message[:max_length] + "..."
    
    if notify:
        notification.notify(
            title="Instagram AutoPost Scheduler",
            message=message,
            app_name="AutoPost Scheduler"
        )
    
    status_var.set(message)
    root.after(0, status_var.set, message)

    

class ToolTip:
    def __init__(self, widget):
        self.widget = widget
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event):
        if self.tooltip_window is not None:
            return
        item = self.widget.identify("item", event.x, event.y)
        if item:
            index = self.widget.item(item)["values"][2]
            x = self.widget.winfo_rootx() + event.x + 20
            y = self.widget.winfo_rooty() + event.y + 20
            self.tooltip_window = tk.Toplevel(self.widget)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.wm_geometry(f"+{x}+{y}")
            label = tk.Label(self.tooltip_window, text=index, background="yellow")
            label.pack()

    def hide_tooltip(self, event):
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None

def refresh_planned_posts():
    for row in tree.get_children():
        tree.delete(row)
    global df
    df.reset_index(drop=True, inplace=True) 
    for index, post in df.iterrows():
        caption_display = post["Caption"].replace("\n", " ")
        if len(caption_display) > 50:
            caption_display = caption_display[:47] + '...'
        
        color = "orange" if not post["Posted"] else "green"
        item = tree.insert("", "end", values=(post["Date and Time"], caption_display, post["Directory"]))
        tree.item(item, tags=(color,)) 

    tree.tag_configure("orange", background="orange")
    tree.tag_configure("green", background="green")
    
    ToolTip(tree)

def delete_post():
    selected_item = tree.selection()
    if selected_item:
        item = selected_item[0]
        item_index = tree.index(item)
        if item_index in df.index:
            df.drop(item_index, inplace=True)
            df.to_excel(file_path, index=False)
            refresh_planned_posts()
            update_status("Post deleted successfully!")
        else:
            messagebox.showwarning("Warning", "Selected post not found in DataFrame.")
    else:
        messagebox.showwarning("Input Error", "No post selected for deletion.")

def add_post():
    def choose_file():
        # Ask the user to select multiple files
        selected_file = filedialog.askopenfilenames(
            title="Select Files",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg"), ("Video Files", "*.mp4")]
        )
        
        # Convert the selected files to a list (it's already a tuple, so no need to list() again)
        selected_file = [path.replace('/', '\\') for path in selected_file]
        
        if selected_file:
            # Join the file paths with a comma and space, and insert it into the entry
            new_template_entry.delete(0, tk.END)
            new_template_entry.insert(0, ', '.join(selected_file))

    def save_new_post():
        date = new_date_entry.get()
        time = new_time_entry.get()
        caption = new_caption_entry.get("1.0", tk.END).strip()
        selected_template = new_template_entry.get()

        if date and time and caption and selected_template:
            date_time_str = f"{date} {time}"
            try:
                datetime.datetime.strptime(date_time_str, '%Y-%m-%d %H:%M')
                new_row = pd.DataFrame({
                    'Date and Time': [date_time_str],
                    'Caption': [caption],
                    'Directory': [selected_template],
                    'Posted': [False]
                })
                global df
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_excel(file_path, index=False)
                refresh_planned_posts()
                new_window.destroy()
            except ValueError:
                messagebox.showwarning("Input Error", "Please enter a valid date and time format.")
        else:
            messagebox.showwarning("Input Error", "Please fill in all fields.")

    new_window = tk.Toplevel(root)
    new_window.grab_set()
    new_window.title("Add Planned Post")
    
    tk.Label(new_window, text="Date (YYYY-MM-DD):").pack()
    new_date_entry = ttk.Entry(new_window)
    new_date_entry.insert(0, current_date) 
    new_date_entry.pack(pady=5)

    tk.Label(new_window, text="Time (HH:MM):").pack()
    new_time_entry = ttk.Entry(new_window)
    new_time_entry.insert(0, current_time)
    new_time_entry.pack(pady=5)

    tk.Label(new_window, text="Caption:").pack()
    new_caption_entry = tk.Text(new_window, height=5, width=40)
    new_caption_entry.pack(pady=5)

    tk.Label(new_window, text="Choose File:").pack()
    new_template_entry = ttk.Entry(new_window)
    new_template_entry.pack(pady=5)

    ttk.Button(new_window, text="Choose File", command=choose_file, style='Choose.TButton', image=upload_icon, compound="left").pack(pady=5)
    ttk.Button(new_window, text="Save Post", command=save_new_post, style='Save.TButton', image=save_icon, compound="left").pack(pady=10)

def edit_post():
    selected_item = tree.selection()
    if selected_item:
        item_index = tree.index(selected_item[0])
        current_post = df.iloc[item_index]

        edit_window = tk.Toplevel(root)
        edit_window.title("Edit Planned Post")

        tk.Label(edit_window, text="Date (YYYY-MM-DD):").pack()
        edit_date_entry = ttk.Entry(edit_window)
        edit_date_entry.insert(0, current_post["Date and Time"].split()[0])
        edit_date_entry.pack(pady=5)

        tk.Label(edit_window, text="Time (HH:MM):").pack()
        edit_time_entry = ttk.Entry(edit_window)
        edit_time_entry.insert(0, current_post["Date and Time"].split()[1])
        edit_time_entry.pack(pady=5)

        tk.Label(edit_window, text="Caption:").pack()
        edit_caption_entry = tk.Text(edit_window, height=5, width=40)
        edit_caption_entry.insert("1.0", current_post["Caption"])
        edit_caption_entry.pack(pady=5)

        tk.Button(edit_window, text="Save Changes", command=lambda: save_changes(item_index, edit_date_entry, edit_time_entry, edit_caption_entry,edit_window), image=save_icon, compound="left").pack(pady=10)
    else:
        messagebox.showwarning("Input Error", "No post selected for editing.")

def save_changes(index, date_entry, time_entry, caption_entry, edit_window):
    date = date_entry.get()
    time = time_entry.get()
    caption = caption_entry.get("1.0", tk.END).strip()
    
    if date and time and caption:
        date_time_str = f"{date} {time}"
        try:
            datetime.datetime.strptime(date_time_str, '%Y-%m-%d %H:%M')
            df.at[index, 'Date and Time'] = date_time_str
            df.at[index, 'Caption'] = caption
            df.to_excel(file_path, index=False)
            refresh_planned_posts()
            update_status("Post edited successfully!")
            edit_window.destroy()
        except ValueError:
            messagebox.showwarning("Input Error", "Please enter a valid date and time format.")
    else:
        messagebox.showwarning("Input Error", "Please fill in all fields.")

root = tk.Tk()
root.title("Autopost")
root.geometry("600x500")
style = Style()
style.configure('Login.TButton', foreground='white', background='#3e74d4')
style.configure('Upload.TButton', foreground='white', background='#2196F3') 
style.configure('Up.TButton', foreground='white', background='#4CAF50') 
style.configure('Down.TButton', foreground='white', background='#F44336') 
style.configure('Share.TButton', foreground='white', background='#4CAF50') 
style.configure('Choose.TButton', foreground='white', background='#2196F3') 
style.configure('Save.TButton', foreground='white', background='#4CAF50') 
style.configure('Schedule.TButton', foreground='white', background='#2196F3') 
style.configure('Add.TButton', foreground='white', background='#4CAF50') 
style.configure('Edit.TButton', foreground='white', background='#2196F3') 
style.configure('Delete.TButton', foreground='white', background='#F44336') 


root.resizable(True, True)
root.iconbitmap(os.path.join(current_dir, "icon", "instagram_logo.ico"))
upload_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "upload_icon.png")).resize((20, 20)))
share_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "share_icon.png")).resize((20, 20)))
schedule_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "schedule_icon.png")).resize((20, 20)))
delete_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "delete_icon.png")).resize((20, 20)))
edit_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "edit_icon.png")).resize((20, 20)))
add_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "add_icon.png")).resize((20, 20)))
save_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "save_icon.png")).resize((20, 20)))
login_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "account_icon.png")).resize((20, 20)))
quick_post_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "quick_icon.png")).resize((20, 20)))
settings_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "settings_icon.png")).resize((20, 20)))
planned_posts_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "planned_icon.png")).resize((20, 20)))
log_icon = ImageTk.PhotoImage(Image.open(os.path.join(current_dir, "icon", "log_icon.png")).resize((20, 20)))



title_frame = tk.Frame(root)
title_frame.pack(pady=10)
title_label = tk.Label(title_frame, text="Social Media AutoPost Scheduler", font=("Arial", 18))
title_label.pack()

status_var = tk.StringVar()
status_bar = tk.Label(root, textvariable=status_var, relief=tk.SUNKEN, anchor="w", image= log_icon, compound="left")
status_bar.pack(side=tk.BOTTOM, fill=tk.X)


tab_control = ttk.Notebook(root)

def login():
    def perform_login():
        global client

        global logged_in
        username = username_entry.get()
        password = password_entry.get()

        try:
            client.login(username, password)

            root.after(0, update_status, "Login successful!")
            root.after(0, switch_to_main_tabs)
            logged_in = True
        except Exception as e:
            root.after(0, update_status, "Login Failed")
            root.after(0, messagebox.showerror, "Login Error", str(e))
            logged_in = False

    threading.Thread(target=perform_login, daemon=True).start()

def linkedin_login():
    """LinkedIn authentication is handled via access token in config.json.

    LinkedIn web-UI automation (cookies / Selenium) is intentionally not included here.
    To enable LinkedIn posting, set:
      - linkedin.enabled = true
      - linkedin.authorUrn
      - linkedin.accessToken
    in config.json.
    """
    messagebox.showinfo(
        "LinkedIn",
        "LinkedIn login is not required in this version.\n"
        "Please configure your LinkedIn API access token in config.json."
    )


def switch_to_main_tabs():
    tab_control.forget(login_tab)
    tab_control.add(quick_post_tab, text='Quick Post', image=quick_post_icon, compound="left")
    tab_control.add(planned_posts_tab, text='Planned Posts', image=planned_posts_icon, compound="left")
    tab_control.add(settings_tab, text='Settings', image=settings_icon, compound="left")
    root.geometry("900x1200")
    tab_control.pack(expand=1, fill="both")
settings_tab = ttk.Frame(tab_control)
tk.Label(settings_tab, text="LinkedIn Username:").pack(pady=10)
linkedin_username_entry = ttk.Entry(settings_tab)
linkedin_username_entry.pack(pady=5)

tk.Label(settings_tab, text="LinkedIn Password:").pack(pady=10)
linkedin_password_entry = ttk.Entry(settings_tab, show="*")
linkedin_password_entry.pack(pady=5)

linkedin_login_button = ttk.Button(settings_tab, text="Login to LinkedIn", command=linkedin_login)
linkedin_login_button.pack(pady=10)
quick_post_tab = ttk.Frame(tab_control)

tk.Label(settings_tab, text="Tags (e.g. #instagram #hi #linkedin):").pack(pady=10)
tags_entry = tk.Text(settings_tab, height=5, width=40)
tags_entry.pack(pady=5)
tags_file = TAGS_FILE
if os.path.exists(tags_file):
    with open(tags_file, 'r', encoding='utf-8') as file:
        tags = file.read().strip()
        tags_entry.insert(tk.END, tags)

def save_tags():
    with open(tags_file, 'w', encoding='utf-8') as file:
        file.write(tags_entry.get("1.0", tk.END).strip())
    messagebox.showinfo("Success", "Tags saved successfully!")

ttk.Button(settings_tab, text="Save Tags", command=save_tags).pack(pady=10)
button_frame = ttk.Frame(quick_post_tab)
button_frame.pack(pady=10)

upload_images_button = ttk.Button(button_frame, text="Upload File(s)", command=upload_images, image=upload_icon, style='Upload.TButton', compound="left")
upload_images_button.grid(row=0, column=1, padx=10)

make_video_button = ttk.Button(button_frame, text="Make Video", command=make_video, style="Upload.TButton", compound="left")
make_video_button.grid(row=0, column=2, padx=10)

listbox = tk.Listbox(quick_post_tab, height=10, width=50)
listbox.pack(pady=10)

adjust_frame = tk.Frame(quick_post_tab)
adjust_frame.pack(pady=5)

move_up_button = ttk.Button(adjust_frame, text="+", command=move_up, style='Up.TButton')
move_up_button.pack(side=tk.LEFT, padx=5)

move_down_button = ttk.Button(adjust_frame, text="-", command=move_down, style='Down.TButton')
move_down_button.pack(side=tk.LEFT, padx=5)

template_var = tk.StringVar(value="Template1")
template_frame = tk.Frame(quick_post_tab)
template_frame.pack(pady=10)

template_paths = {
    "Template1": os.path.join(current_dir, "template01.jpg"),
    "Template2": os.path.join(current_dir, "template02.jpg"),
}

for template_name, img_path in template_paths.items():
    try:
        img = Image.open(img_path).resize((125, 125))
        photo = ImageTk.PhotoImage(img)
        template_images[template_name] = photo 
        tk.Radiobutton(template_frame, text=template_name, variable=template_var, value=template_name,
                       image=photo, compound="top").pack(side=tk.LEFT, padx=10)
    except Exception as e:
        messagebox.showerror("File Load Error", f"Could not load {template_name}: {str(e)}")

template_frame.pack(side=tk.TOP, pady=10)
simdi = datetime.datetime.now()
current_date = simdi.strftime("%Y-%m-%d")
current_time = simdi.strftime("%H:%M")

tk.Label(quick_post_tab, text="Date (YYYY-MM-DD):").pack()
date_entry = ttk.Entry(quick_post_tab)
date_entry.insert(0, current_date) 
date_entry.pack(pady=5)

tk.Label(quick_post_tab, text="Time (HH:MM):").pack()
time_entry = ttk.Entry(quick_post_tab)
time_entry.insert(0, current_time)
time_entry.pack(pady=5)

tk.Label(quick_post_tab, text="Caption:").pack()
caption_entry = tk.Text(quick_post_tab, height=5, width=40)
caption_entry.pack(pady=5)
''' 
caption_entry.insert(tk.END, "\n\n")
#CAPTİON TAG

tags_file = "tags.txt"
if os.path.exists(tags_file):
    with open(tags_file, 'r') as file:
        tags = file.read().strip()
        caption_entry.insert(tk.END, tags)
'''
button_frame = tk.Frame(quick_post_tab)

button_frame.pack(pady=10)
ttk.Button(button_frame, text="Share Now", command=share_now, style='Share.TButton', image=share_icon, compound="left").pack(side=tk.LEFT, padx=10)
ttk.Button(button_frame, text="Schedule Post", command=schedule_post, style='Schedule.TButton', image=schedule_icon, compound="left").pack(side=tk.LEFT, padx=10)

planned_posts_tab = ttk.Frame(tab_control)

tree = ttk.Treeview(planned_posts_tab, columns=("Date and Time", "Caption", "Directory"), show='headings')
tree.heading("Date and Time", text="Date and Time")
tree.heading("Caption", text="Caption")
tree.heading("Directory", text="Directory")
tree.pack(fill=tk.BOTH, expand=True)

ttk.Button(planned_posts_tab, text="Add Post", command=add_post, style='Add.TButton', image=add_icon, compound="left").pack(pady=10)
ttk.Button(planned_posts_tab, text="Edit Selected", command=edit_post, style='Edit.TButton', image=edit_icon, compound="left").pack(pady=10)
ttk.Button(planned_posts_tab, text="Delete Selected", command=delete_post, style='Delete.TButton', image=delete_icon, compound="left").pack(pady=10)


tab_control.pack(expand=1, fill="both")
refresh_planned_posts()

def on_tab_change(event):
    selected_tab = tab_control.index(tab_control.select())
    if selected_tab == 1:  
        refresh_planned_posts()

tab_control.bind("<<NotebookTabChanged>>", on_tab_change)

#refresh_planned_posts()  

def check_scheduled_posts():
    while True:
        now = datetime.datetime.now()
        for index, post in df.iterrows():
            post_time = datetime.datetime.strptime(post["Date and Time"], '%Y-%m-%d %H:%M')
            if post["Posted"] == False and post_time <= now:
                try:
                    directories = post["Directory"].split(",")
                    directories = [dir.strip() for dir in directories]

                    # Caption kontrolü
                    caption = post["Caption"]
                    if isinstance(caption, str):  # Eğer Caption bir string ise
                        caption_display = caption.replace("\n", " ")
                    else:
                        caption_display = ""  # Eğer geçerli bir metin değilse, boş bir string

                    def upload_to_platforms():
                        try:
                            if not is_logged_in():
                               update_status("User is not logged in. Post was not shared.")
                               return
                            if len(directories) > 1:
                                success = linkedin(caption_display, directories)
                                if success:
                                    success = client.album_upload(directories, caption_display)
                                    if success:
                                        update_status("Album posted successfully!")
                                    else:
                                        update_status("Instagram post failed!")
                                else:
                                    update_status("LinkedIn post failed!")
                            else:
                                if directories[0].endswith('.mp4'):
                                    success = linkedin(caption_display, directories)
                                    if success:
                                        success = client.clip_upload(directories[0], caption_display)
                                        if success:
                                            update_status("Video posted successfully!")
                                        else:
                                            update_status("Instagram video post failed!")
                                    else:
                                        update_status("LinkedIn video post failed!")
                                else:
                                    success = linkedin(caption_display, directories)
                                    if success:
                                        success = client.photo_upload(directories[0], caption_display)
                                        if success:
                                            update_status("Photo posted successfully!")
                                        else:
                                            update_status("Instagram photo post failed!")
                                    else:
                                        update_status("LinkedIn photo post failed!")

                            # Mark the shared post
                            matching_row = df[df['Caption'] == caption]  # Find the matching post based on the caption.
                            if not matching_row.empty:
                                # Eşleşen postu bulup "Posted" kolonunu True yap
                                df.loc[matching_row.index[0], "Posted"] = True  # Set the "Posted" column to True for the shared post.
                                df.to_excel(file_path, index=False)
                            update_status(f"Shared scheduled post: {caption_display}", notify=True)

                        except Exception as e:
                            update_status(f"Failed to share post: {str(e)}", notify=True)

                    threading.Thread(target=upload_to_platforms, daemon=True).start()

                except Exception as e:
                    update_status(f"Failed to process scheduled post: {str(e)}", notify=True)
                
        refresh_planned_posts()
        time.sleep(60)



scheduler_thread = threading.Thread(target=check_scheduled_posts, daemon=True)
scheduler_thread.start()

root.mainloop()