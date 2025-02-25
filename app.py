from flask import Flask, redirect, request, session, url_for, render_template, flash
import requests
import os
import pandas as pd
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecret")

# 📌 Facebook OAuth Config
# FACEBOOK_APP_ID = "YOUR_FACEBOOK_APP_ID"
# FACEBOOK_APP_SECRET = "YOUR_FACEBOOK_APP_SECRET"
REDIRECT_URI = "https://postfbweb.onrender.com/facebook_callback"
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")

UPLOAD_FOLDER = "uploads"
VIDEO_FOLDER = "videos"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# 📌 Trang chính
@app.route("/")
def index():
    return render_template("index.html")

# 📌 Bắt đầu đăng nhập Facebook
@app.route("/login")
def login():
    fb_auth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth?"
        f"client_id={FACEBOOK_APP_ID}&redirect_uri={REDIRECT_URI}&scope=pages_show_list,pages_manage_posts,public_profile"
        # f"client_id={FACEBOOK_APP_ID}&redirect_uri={REDIRECT_URI}&scope=pages_show_list,pages_manage_posts"
    )
    return redirect(fb_auth_url)

# 📌 Xử lý đăng nhập Facebook
@app.route("/facebook_callback")
def facebook_callback():
    code = request.args.get("code")
    if not code:
        return "❌ Đăng nhập thất bại", 400

    token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
    params = {
        "client_id": FACEBOOK_APP_ID,
        "client_secret": FACEBOOK_APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    response = requests.get(token_url, params=params)
    data = response.json()

    if "access_token" in data:
        session["access_token"] = data["access_token"]
        return redirect(url_for("select_page"))  # 👉 Chuyển hướng về trang chọn Page

    return "❌ Đăng nhập thất bại", 400

# 📌 Trang Dashboard
@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect(url_for("login"))

    access_token = session["access_token"]
    pages_url = f"https://graph.facebook.com/v18.0/me/accounts?access_token={access_token}"
    
    response = requests.get(pages_url)
    pages = response.json().get("data", [])

    return render_template("dashboard.html", pages=pages)

#chọn page
@app.route("/select_page", methods=["GET", "POST"])
def select_page():
    if "access_token" not in session:
        return redirect(url_for("login"))

    access_token = session["access_token"]
    pages_url = f"https://graph.facebook.com/v18.0/me/accounts?access_token={access_token}"

    response = requests.get(pages_url)
    pages = response.json().get("data", [])

    if request.method == "POST":
        session["selected_page_id"] = request.form.get("page_id")
        session["selected_page_name"] = request.form.get("page_name")

        if not session["selected_page_id"]:
            flash("⚠️ Bạn chưa chọn Page!", "danger")
            return redirect(url_for("select_page"))

        return redirect(url_for("upload_page"))  # 👉 Chuyển sang upload file

    return render_template("select_page.html", pages=pages)



#upload page

@app.route("/upload_page", methods=["GET", "POST"])
def upload_page():
    if "selected_page_id" not in session:
        return redirect(url_for("select_page"))

    page_name = session.get("selected_page_name", "Trang chưa xác định")
    return render_template("upload.html", page_name=page_name)

# 📌 Xử lý Upload File Excel
process_message = "Chưa có tiến trình nào"

@app.route("/upload", methods=["POST"])
def upload_file():
    global process_message

    if "file" not in request.files:
        process_message = "⚠️ Không có file nào được chọn!"
        return redirect(url_for("upload_page"))

    file = request.files["file"]
    if file.filename == "":
        process_message = "⚠️ Chưa chọn file!"
        return redirect(url_for("upload_page"))

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    process_message = "✅ File đã tải lên thành công! Đang xử lý..."
    threading.Thread(target=schedule_videos, args=(file_path,)).start()

    return redirect(url_for("upload_page"))

@app.route("/status")
def status():
    return {"message": process_message}


# 📌 Tự động đăng video từ file Excel
def schedule_videos(file_path):
    global process_message

    df = pd.read_excel(file_path)
    page_id = session.get("selected_page_id")

    if not page_id:
        process_message = "⚠️ Chưa chọn Page!"
        return

    process_message = f"📌 Đang xử lý {len(df)} video..."

    for index, row in df.iterrows():
        video_stt = str(int(row["STT"]))
        video_path = os.path.join(VIDEO_FOLDER, f"{video_stt}.mp4")

        if not os.path.exists(video_path):
            process_message = f"❌ Không tìm thấy video {video_path}"
            continue

        caption = row["Caption"]
        post_time = row["Thời Gian Đăng"]
        post_datetime = datetime.strptime(post_time, "%Y-%m-%d %H:%M")
        now = datetime.now()
        wait_time = (post_datetime - now).total_seconds()

        if wait_time > 0:
            process_message = f"⏳ Chờ {wait_time//60} phút để đăng video {video_stt}"
            time.sleep(wait_time)

        upload_video(video_path, caption, page_id)

    process_message = "✅ Tất cả video đã đăng thành công!"


# 📌 Đăng video lên Facebook
def upload_video(video_path, caption, page_id):
    global process_message

    access_token = session["access_token"]
    file_size = os.path.getsize(video_path)
    start_url = f"https://graph.facebook.com/v18.0/{page_id}/video_reels"

    start_params = {
        "upload_phase": "start",
        "access_token": access_token,
        "file_size": file_size
    }

    start_response = requests.post(start_url, data=start_params)
    start_data = start_response.json()

    if "video_id" not in start_data or "upload_url" not in start_data:
        process_message = f"❌ Lỗi khi lấy upload_url: {start_data}"
        return

    video_id = start_data["video_id"]
    upload_url = start_data["upload_url"]

    with open(video_path, "rb") as video_file:
        upload_response = requests.post(upload_url, data=video_file)

    finish_url = f"https://graph.facebook.com/v18.0/{page_id}/video_reels"
    finish_params = {
        "upload_phase": "finish",
        "access_token": access_token,
        "video_id": video_id,
        "description": caption,
        "published": "true",
    }

    finish_response = requests.post(finish_url, data=finish_params)
    finish_data = finish_response.json()

    if "id" in finish_data:
        process_message = f"✅ Đăng thành công Video ID: {finish_data['id']}"
    else:
        process_message = f"❌ Lỗi đăng video: {finish_data}"


# 📌 Chạy Flask
if __name__ == "__main__":
    app.run(debug=True)
