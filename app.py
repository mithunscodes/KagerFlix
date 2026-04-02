import os
import uuid
import json
import subprocess
import threading
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import ClientError
from database import db, Video, User, init_db

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///videos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSED_FOLDER'] = 'processed'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# AWS S3 Config (optional — falls back to local storage if not set)
AWS_BUCKET = os.environ.get('AWS_S3_BUCKET', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)

db.init_app(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv'}

def admin_required(f):
    """Decorator to require admin privileges."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_s3_client():
    if not AWS_BUCKET:
        return None
    return boto3.client('s3', region_name=AWS_REGION)

def upload_to_s3(file_path, s3_key):
    s3 = get_s3_client()
    if not s3:
        return None
    try:
        s3.upload_file(file_path, AWS_BUCKET, s3_key)
        return f"https://{AWS_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
    except ClientError as e:
        print(f"S3 upload error: {e}")
        return None

def get_video_metadata(filepath):
    """Extract metadata using FFprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            fmt = data.get('format', {})
            streams = data.get('streams', [])
            video_stream = next((s for s in streams if s.get('codec_type') == 'video'), {})
            return {
                'duration': float(fmt.get('duration', 0)),
                'size': int(fmt.get('size', 0)),
                'bitrate': int(fmt.get('bit_rate', 0)),
                'width': video_stream.get('width', 0),
                'height': video_stream.get('height', 0),
                'codec': video_stream.get('codec_name', 'unknown'),
                'fps': eval(video_stream.get('r_frame_rate', '0/1')) if video_stream.get('r_frame_rate') else 0,
            }
    except Exception as e:
        print(f"FFprobe error: {e}")
    return {}

def generate_thumbnail(input_path, output_path, timestamp='00:00:02'):
    """Generate thumbnail using FFmpeg."""
    try:
        # Scale to fit within 640x640 while maintaining aspect ratio
        cmd = [
            'ffmpeg', '-i', input_path,
            '-ss', timestamp, '-vframes', '1',
            '-vf', 'scale=640:640:force_original_aspect_ratio=decrease,pad=640:640:(ow-iw)/2:(oh-ih)/2',
            '-y', output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.returncode == 0
    except Exception as e:
        print(f"Thumbnail error: {e}")
        return False

def transcode_video(video_id):
    """Transcode video to HLS format for adaptive streaming."""
    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            return

        video.status = 'processing'
        db.session.commit()

        input_path = video.file_path
        output_dir = os.path.join(app.config['PROCESSED_FOLDER'], str(video_id))
        os.makedirs(output_dir, exist_ok=True)

        # Generate thumbnail
        thumb_path = os.path.join(output_dir, 'thumbnail.jpg')
        generate_thumbnail(input_path, thumb_path)
        if os.path.exists(thumb_path):
            video.thumbnail_path = thumb_path

        # Transcode to HLS with multiple quality levels
        # Define target heights and bitrates, scale width to maintain aspect ratio
        qualities = [
            ('360p', 360, '800k', '96k'),
            ('720p', 720, '2500k', '128k'),
            ('1080p', 1080, '5000k', '192k'),
        ]

        hls_output = os.path.join(output_dir, 'stream.m3u8')
        variant_streams = []

        for label, max_height, vbitrate, abitrate in qualities:
            quality_dir = os.path.join(output_dir, label)
            os.makedirs(quality_dir, exist_ok=True)
            playlist = os.path.join(quality_dir, 'index.m3u8')
            segment = os.path.join(quality_dir, 'seg%03d.ts')

            # Scale to maintain aspect ratio: -2 means FFmpeg calculates the dimension
            # This ensures portrait videos stay portrait and landscape stay landscape
            cmd = [
                'ffmpeg', '-i', input_path,
                '-vf', f'scale=-2:{max_height}',
                '-c:v', 'libx264', '-b:v', vbitrate, '-maxrate', vbitrate, '-bufsize', str(int(vbitrate[:-1])*2)+'k',
                '-c:a', 'aac', '-b:a', abitrate,
                '-hls_time', '6', '-hls_list_size', '0',
                '-hls_segment_filename', segment,
                '-y', playlist
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode == 0:
                bandwidth = int(vbitrate[:-1]) * 1000
                variant_streams.append(f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={label}\n{label}/index.m3u8')

        # Write master playlist
        if variant_streams:
            with open(hls_output, 'w') as f:
                f.write('#EXTM3U\n')
                f.write('\n'.join(variant_streams))
            video.hls_path = hls_output
            video.status = 'ready'
        else:
            # Fallback: just mark original as ready
            video.status = 'ready'

        # Upload to S3 if configured
        if AWS_BUCKET and os.path.exists(output_dir):
            s3_url = upload_to_s3(hls_output, f'videos/{video_id}/stream.m3u8')
            if s3_url:
                video.s3_url = s3_url

        video.processed_at = datetime.utcnow()
        db.session.commit()

# ─── Routes ───────────────────────────────────────────────

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not username or not email or not password:
            return render_template('signup.html', error='All fields are required')

        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match')

        if User.query.filter_by(username=username).first():
            return render_template('signup.html', error='Username already exists')

        if User.query.filter_by(email=email).first():
            return render_template('signup.html', error='Email already exists')

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            is_admin=False
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for('index'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('login.html', error='Username and password are required')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/')
def index():
    videos = Video.query.filter_by(status='ready').order_by(Video.created_at.desc()).all()
    return render_template('index.html', videos=videos)

@app.route('/dashboard')
@login_required
def dashboard():
    videos = Video.query.order_by(Video.created_at.desc()).all()
    stats = {
        'total': len(videos),
        'ready': sum(1 for v in videos if v.status == 'ready'),
        'processing': sum(1 for v in videos if v.status == 'processing'),
        'total_views': sum(v.views for v in videos),
        'total_size': sum(v.file_size or 0 for v in videos),
    }
    return render_template('dashboard.html', videos=videos, stats=stats)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'video' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['video']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        filename = secure_filename(file.filename)
        video_id = str(uuid.uuid4())
        ext = filename.rsplit('.', 1)[1].lower()
        saved_name = f"{video_id}.{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
        file.save(file_path)

        # Get metadata
        meta = get_video_metadata(file_path)

        video = Video(
            id=video_id,
            user_id=current_user.id,
            title=request.form.get('title', filename.rsplit('.', 1)[0]),
            description=request.form.get('description', ''),
            filename=saved_name,
            file_path=file_path,
            file_size=meta.get('size', os.path.getsize(file_path)),
            duration=meta.get('duration', 0),
            width=meta.get('width', 0),
            height=meta.get('height', 0),
            codec=meta.get('codec', ''),
            status='queued',
            created_at=datetime.utcnow(),
        )
        db.session.add(video)
        db.session.commit()

        # Start transcoding in background
        thread = threading.Thread(target=transcode_video, args=(video_id,))
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'video_id': video_id, 'redirect': url_for('watch', video_id=video_id)})

    return render_template('upload.html')

@app.route('/watch/<video_id>')
def watch(video_id):
    video = Video.query.get_or_404(video_id)
    video.views += 1
    db.session.commit()
    related = Video.query.filter(Video.id != video_id, Video.status == 'ready').limit(6).all()
    return render_template('watch.html', video=video, related=related)

@app.route('/stream/<video_id>/master.m3u8')
def stream_master(video_id):
    video = Video.query.get_or_404(video_id)
    if video.hls_path and os.path.exists(video.hls_path):
        return send_file(video.hls_path, mimetype='application/vnd.apple.mpegurl')
    return jsonify({'error': 'Stream not available'}), 404

@app.route('/stream/<video_id>/<quality>/index.m3u8')
def stream_quality(video_id, quality):
    path = os.path.join(app.config['PROCESSED_FOLDER'], video_id, quality, 'index.m3u8')
    if os.path.exists(path):
        return send_file(path, mimetype='application/vnd.apple.mpegurl')
    return jsonify({'error': 'Not found'}), 404

@app.route('/stream/<video_id>/<quality>/<segment>')
def stream_segment(video_id, quality, segment):
    path = os.path.join(app.config['PROCESSED_FOLDER'], video_id, quality, segment)
    if os.path.exists(path):
        return send_file(path, mimetype='video/MP2T')
    return jsonify({'error': 'Not found'}), 404

@app.route('/stream/<video_id>/direct')
def stream_direct(video_id):
    video = Video.query.get_or_404(video_id)
    if not os.path.exists(video.file_path):
        return jsonify({'error': 'File not found'}), 404

    range_header = request.headers.get('Range', None)
    file_size = os.path.getsize(video.file_path)

    if range_header:
        byte_start, byte_end = 0, file_size - 1
        parts = range_header.replace('bytes=', '').split('-')
        if parts[0]:
            byte_start = int(parts[0])
        if parts[1]:
            byte_end = int(parts[1])
        length = byte_end - byte_start + 1

        def generate():
            with open(video.file_path, 'rb') as f:
                f.seek(byte_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        resp = Response(generate(), 206, mimetype='video/mp4', direct_passthrough=True)
        resp.headers.add('Content-Range', f'bytes {byte_start}-{byte_end}/{file_size}')
        resp.headers.add('Accept-Ranges', 'bytes')
        resp.headers.add('Content-Length', length)
        return resp

    return send_file(video.file_path, mimetype='video/mp4')

@app.route('/thumbnail/<video_id>')
def thumbnail(video_id):
    video = Video.query.get_or_404(video_id)
    if video.thumbnail_path and os.path.exists(video.thumbnail_path):
        return send_file(video.thumbnail_path, mimetype='image/jpeg')
    # Return a placeholder SVG
    svg = '''<svg width="640" height="360" xmlns="http://www.w3.org/2000/svg">
        <rect width="640" height="360" fill="#1a1a2e"/>
        <text x="320" y="190" text-anchor="middle" fill="#4a4a6a" font-size="24" font-family="sans-serif">No Thumbnail</text>
    </svg>'''
    return Response(svg, mimetype='image/svg+xml')

@app.route('/api/video/<video_id>')
def api_video(video_id):
    video = Video.query.get_or_404(video_id)
    return jsonify(video.to_dict())

@app.route('/api/video/<video_id>', methods=['DELETE'])
@admin_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    # Clean up files
    for path in [video.file_path, video.thumbnail_path, video.hls_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
    # Also clean up the processed directory
    output_dir = os.path.join(app.config['PROCESSED_FOLDER'], str(video_id))
    if os.path.exists(output_dir):
        try:
            import shutil
            shutil.rmtree(output_dir)
        except:
            pass
    
    db.session.delete(video)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/video/<video_id>', methods=['PATCH'])
def update_video(video_id):
    video = Video.query.get_or_404(video_id)
    data = request.json
    if 'title' in data:
        video.title = data['title']
    if 'description' in data:
        video.description = data['description']
    db.session.commit()
    return jsonify(video.to_dict())

@app.route('/api/stats')
def api_stats():
    videos = Video.query.all()
    return jsonify({
        'total_videos': len(videos),
        'ready': sum(1 for v in videos if v.status == 'ready'),
        'processing': sum(1 for v in videos if v.status == 'processing'),
        'total_views': sum(v.views for v in videos),
        'storage_used_mb': round(sum(v.file_size or 0 for v in videos) / 1024 / 1024, 2),
    })

@app.route('/setup-admin', methods=['GET', 'POST'])
def setup_admin():
    """Setup admin user. Only works if no admin exists yet."""
    with app.app_context():
        admin_exists = User.query.filter_by(is_admin=True).first()
        
        if admin_exists:
            return jsonify({'error': 'Admin already exists'}), 400
        
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            
            if not username or not email or not password:
                return render_template('setup_admin.html', error='All fields are required')
            
            # Check if username or email already exist
            if User.query.filter_by(username=username).first():
                return render_template('setup_admin.html', error='Username already exists')
            if User.query.filter_by(email=email).first():
                return render_template('setup_admin.html', error='Email already exists')
            
            admin = User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                is_admin=True
            )
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            
            login_user(admin)
            return redirect(url_for('index'))
        
        return render_template('setup_admin.html')

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    with app.app_context():
        init_db(app)
    app.run(debug=True, host='0.0.0.0', port=5000)
