from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
import googleapiclient.discovery
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from bson import ObjectId
from forms import TodoForm
from flask_pymongo import PyMongo
from markupsafe import Markup
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session


# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = 'secret_key'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['lifehub_db']
users_collection = db['users_sitteings']
activity_collection = db['activity_logs']
events_collection = db['events_calender']

# Flask-PyMongo setup

app = Flask(__name__)
app.secret_key = 'secret_key'
app.config["SECRET_KEY"] = "f2330203d221db94b14488386f4ba3a5b0ee38c2b966327a"
app.config["MONGO_URI"] = "mongodb://localhost:27017/lifehub_db"
mongodb_client = PyMongo(app)
db = mongodb_client.db

habit_db = client['amitdb']
habits_collection = habit_db['habits']

# YouTube API setup
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Email setup
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.start()

# Allowed image extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Utility functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def search_youtube(query):
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(q=query, part="snippet", type="video", maxResults=5)
    response = request.execute()

    video_links = []
    for item in response['items']:
        video_id = item['id']['videoId']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_links.append(video_url)

    return video_links

def send_reminder(event_name, event_date, email):
    subject = f"Reminder: Upcoming Event - {event_name}"
    body = f"Hi there,\n\nThis is a reminder for your upcoming event:\n\nEvent: {event_name}\nDate: {event_date}\n\nBest regards, LifeHub."

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, email, msg.as_string())
    except Exception as e:
        print(f"Error sending reminder: {e}")

# Routes
@app.route('/')
def home():
    if 'user_id' in session:
        return render_template('index.html') 
    else:
        return redirect(url_for('registration'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = db.users.find_one({'email': email})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['first_name'] = user['first_name']
            flash(f"Welcome back, {user['first_name']}!", 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password. Please try again.', 'danger')

    return render_template('login.html')

@app.route('/registration', methods=['GET', 'POST'])
def registration():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        user_by_username = db.users.find_one({'username': username})
        user_by_email = db.users.find_one({'email': email})

        if user_by_username:
            flash('Username already exists!', 'danger')
        elif user_by_email:
            flash('Email already exists!', 'danger')
        else:
            db.users.insert_one({
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'email': email,
                'password': hashed_password,
                'date_registered': datetime.utcnow()
            })
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('registration.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = db.users.find_one({'email': email})
        if user:
            # Here you should actually send a password reset link
            flash(f"A password reset link has been sent to {email}.", 'info')
        else:
            flash("Email not found in our records.", 'danger')

    return render_template('forgot_password.html')

@app.route("/view_todos", methods=["GET"])
def get_todos():
    if 'user_id' not in session:  
        flash("Please log in to view tasks.", "danger")
        return redirect(url_for('login'))
    
    filter_option = request.args.get("filter", "all")
    todos = []

    # Adjusting query to filter todos based on completion status
    query = {"user_id": session['user_id']}
    if filter_option == "completed":
        query = {"completed": "True"}
    elif filter_option == "not_completed":
        query = {"completed": "False"}
    else:
        query = {}

    # Fetch todos from MongoDB, sorting by date created
    for todo in db.todos_flask.find(query).sort("date_created", -1):
        todo["_id"] = str(todo["_id"])
        todo["date_created"] = todo["date_created"].strftime("%b %d %Y %H:%M:%S")
        todos.append(todo)

    return render_template("view_todos.html", todos=todos, filter_option=filter_option)

@app.route("/add_todo", methods=["POST", "GET"])
def add_todo():
    if 'user_id' not in session:  # التأكد من تسجيل الدخول
        flash("Please log in to add tasks.", "danger")
        return redirect(url_for('login'))

    form = TodoForm(request.form)
    if request.method == "POST" and form.validate():
        todo_data = {
            "user_id": session['user_id'],
            "name": form.name.data,
            "description": form.description.data,
            "completed": form.completed.data,
            "due_date": form.due_date.data.strftime("%Y-%m-%d"),
            "priority": form.priority.data,
            "date_created": datetime.utcnow(),
        }
        db.todos_flask.insert_one(todo_data)
        flash("Todo successfully added", "success")
        return redirect(url_for('get_todos'))

    return render_template("add_todo.html", form=form)

@app.route("/update_todo/<id>", methods=["POST", "GET"])
def update_todo(id):
    if 'user_id' not in session:
        flash("Please log in to update tasks.", "danger")
        return redirect(url_for('login'))
    form = TodoForm(request.form)
    if request.method == "POST" and form.validate():
        updated_data = {
            "name": form.name.data,
            "description": form.description.data,
            "completed": form.completed.data,
            "due_date": form.due_date.data.strftime("%Y-%m-%d") if form.due_date.data else None,
            "priority": form.priority.data,
        }
        db.todos_flask.update_one(
            {"_id": ObjectId(id), "user_id": session['user_id']},
            {"$set": updated_data}
        )
        flash("Todo successfully updated", "success")
        return redirect(url_for('get_todos'))

    todo = db.todos_flask.find_one({"_id": ObjectId(id), "user_id": session['user_id']})
    if todo:
        form.name.data = todo.get("name")
        form.description.data = todo.get("description")
        form.completed.data = todo.get("completed")
        form.due_date.data = datetime.strptime(todo.get("due_date"), "%Y-%m-%d") if todo.get("due_date") else None
        form.priority.data = todo.get("priority")

    return render_template("add_todo.html", form=form)

@app.route("/delete_todo/<id>")
def delete_todo(id):
    if 'user_id' not in session:
        flash("Please log in to delete tasks.", "danger")
        return redirect(url_for('login'))

    result = db.todos_flask.delete_one({"_id": ObjectId(id), "user_id": session['user_id']})
    if result.deleted_count == 0:
        flash("Task not found or access denied.", "danger")
    else:
        flash("Todo successfully deleted", "success")

    return redirect(url_for('get_todos'))


@app.route("/view_todo/<id>")
def view_todo(id):
    todo = db.todos_flask.find_one({"_id": ObjectId(id)})
    if not todo:
        flash("Todo not found", "danger")
        return redirect(url_for('get_todos'))
    todo["_id"] = str(todo["_id"])
    todo["date_created"] = todo["date_created"].strftime("%b %d %Y %H:%M:%S")
    return render_template("view_todo.html", todo=todo)

def send_reminder(habit_name, email):
    subject = f"Reminder: {habit_name} is due soon!"
    body = f"Hi,\n\nThis is a reminder that your habit '{habit_name}' is due in 10 minutes.\n\nBest regards,\nLifeHub."

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, email, msg.as_string())
        print(f"Reminder sent for habit: {habit_name}")
    except Exception as e:
        print(f"Error sending reminder: {e}")

def schedule_habit_reminder(habit):
    reminder_time = habit.get("reminder_time")
    frequency = habit.get("frequency")  # in hours
    if reminder_time and frequency:
        next_reminder = reminder_time - timedelta(minutes=10)
        scheduler.add_job(
            send_reminder,
            'interval',
            hours=frequency,
            next_run_time=next_reminder,
            args=[habit["name"], SENDER_EMAIL]
        )

@app.route('/habit')
def habit():
    if 'user_id' not in session:
        flash("Please log in to view your habits.", "danger")
        return redirect(url_for('login'))

    habits = list(habits_collection.find({"user_id": session['user_id']}))
    now = datetime.now()

    for habit in habits:
        if "confirmation_count" not in habit:
            habit["confirmation_count"] = {}

        current_date = now.date().isoformat()
        confirmation_count = habit["confirmation_count"].get(current_date, 0)
        if confirmation_count > 0:
            habit["streak"] += 1

        habits_collection.update_one(
            {"_id": habit["_id"], "user_id": session['user_id']},
            {"$set": {"streak": habit["streak"], "last_updated": now.isoformat()}}
        )

    return render_template("habit.html", habits=habits)

@app.route("/confirm_habit", methods=["POST"])
def confirm_habit():
    habit_id = request.form.get("habit_id")
    if not habit_id:
        flash("Habit ID is missing!", "error")
        return redirect(url_for("habit"))

    habit = habits_collection.find_one({"_id": ObjectId(habit_id)})
    if not habit:
        flash("Habit not found!", "error")
        return redirect(url_for("habit"))

    now = datetime.now()
    last_confirmed = habit.get("last_confirmed")
    if last_confirmed:
        last_confirmed = datetime.strptime(last_confirmed, '%Y-%m-%dT%H:%M:%S.%f')

    # Check if confirmation is allowed based on frequency
    if last_confirmed and (now - last_confirmed < timedelta(hours=habit.get("frequency", 1))):
        flash("You can only confirm this habit once every {} hours!".format(habit.get("frequency")), "info")
    else:
        # Update habit confirmation details
        habits_collection.update_one(
            {"_id": ObjectId(habit_id)},
            {"$set": {
                "last_confirmed": now.strftime('%Y-%m-%dT%H:%M:%S.%f'),
                "today_count": habit.get("today_count", 0) + 1
            }}
        )
        flash("Habit confirmed successfully!", "success")

    return redirect(url_for("habit"))

@app.route("/view_activity", methods=["GET"])
def view_activity():
    habit_id = request.args.get("habit_id")
    if not habit_id:
        flash("No habit ID provided!", "error")
        return redirect(url_for("habit"))

    habit = habits_collection.find_one({"_id": ObjectId(habit_id)})
    if not habit:
        flash("Habit not found!", "error")
        return redirect(url_for("habit"))

    last_confirmed = habit.get("last_confirmed", "Not confirmed yet")
    today_count = habit.get("today_count", 0)

    return render_template("view_activity.html", last_confirmed=last_confirmed, today_count=today_count)
@app.route("/add_habit", methods=["GET", "POST"])
def add_habit():
    if 'user_id' not in session:
        flash("Please log in to add habits.", "danger")
        return redirect(url_for('login'))

    if request.method == "POST":
        habit_name = request.form.get("habit_name")
        description = request.form.get("description")
        frequency = int(request.form.get("frequency"))  # Frequency in hours
        reminder_time = datetime.strptime(request.form.get("reminder_time"), "%Y-%m-%dT%H:%M")

        if not habit_name or not description or not frequency or not reminder_time:
            flash("Please fill out all fields.")
            return redirect(url_for("add_habit"))

        habit = {
            "user_id": session['user_id'],  # إضافة user_id
            "name": habit_name,
            "description": description,
            "frequency": frequency,
            "streak": 0,
            "last_updated": None,
            "last_confirmed": None,
            "confirmation_count": {},
            "reminder_time": reminder_time
        }
        habits_collection.insert_one(habit)
        flash("Habit added successfully!", "success")
        return redirect(url_for("habit"))

    return render_template("add_habit.html")


@app.route("/update_habit", methods=["GET", "POST"])
def update_habit():
    habit_id = request.args.get("habit_id")
    if not habit_id:
        flash("No habit ID provided.")
        return redirect(url_for("habit"))

    habit = habits_collection.find_one({"_id": ObjectId(habit_id)})
    if not habit:
        flash("Habit not found.")
        return redirect(url_for("habit"))

    if request.method == "POST":
        habit_name = request.form.get("habit_name")
        description = request.form.get("description")
        frequency = int(request.form.get("frequency"))
        reminder_time = datetime.strptime(request.form.get("reminder_time"), "%Y-%m-%dT%H:%M")

        if not habit_name or not description or not frequency or not reminder_time:
            flash("Please fill out all fields.")
            return redirect(url_for("update_habit", habit_id=habit_id))

        updated_fields = {
            "name": habit_name,
            "description": description,
            "frequency": frequency,
            "reminder_time": reminder_time
        }
        habits_collection.update_one({"_id": ObjectId(habit_id)}, {"$set": updated_fields})
        flash("Habit updated successfully!", "success")
        return redirect(url_for("habit"))

    return render_template("update_habit.html", habit=habit)

@app.route('/remove_habit', methods=['POST'])
def remove_habit():

    habit_id = request.form.get('habit_id')
    if not habit_id:
        flash('Habit ID is missing!', 'error')
        return redirect(url_for('habit')) 

    try:
        result = habits_collection.delete_one({"_id": ObjectId(habit_id)})
        if result.deleted_count == 0:
            flash('No habit found with the provided ID.', 'error')
        else:
            flash('Habit removed successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred while removing the habit: {e}', 'error')

    return redirect(url_for('habit')) 

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = users_collection.find_one()
    if request.method == 'POST':
        username = request.form.get('username')
        address = request.form.get('address')
        phone = request.form.get('phone')
        file = request.files.get('profile_picture')

        if not username:
            flash("Username cannot be empty!", 'error')
            return redirect(url_for('profile'))

        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile_picture_path = os.path.join('uploads', filename)
        else:
            profile_picture_path = user.get('profile_picture', 'uploads/default.png')

        users_collection.update_one({}, {'$set': {
            'username': username,
            'address': address,
            'phone': phone,
            'profile_picture': profile_picture_path
        }}, upsert=True)

        flash("Profile updated successfully!", 'success')
        return redirect(url_for('profile'))

    if not user:
        user = {'username': 'New User', 'profile_picture': 'uploads/default.png', 'address': '', 'phone': ''}
        users_collection.insert_one(user)

    return render_template('profile.html', user=user)

@app.route('/log_activity', methods=['POST', 'GET'])
def log_activity():
    if 'user_id' not in session:
        flash("Please log in to log activities.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        weight = float(request.form['weight'])
        activity_type = request.form['activity_type']
        duration = float(request.form['duration'])

        # Calculate calories burned
        calories = (10.0 if activity_type == 'running' else 7.5 if activity_type == 'cycling' else 3.8) * weight * duration / 60
        
        activity_collection.insert_one({
            'user_id': session['user_id'],  # إضافة user_id
            'weight': weight,
            'activity_type': activity_type,
            'duration': duration,
            'calories_burned': round(calories, 2),
            'timestamp': datetime.now()
        })
        
        flash("Activity logged successfully!", "success")
        return redirect(url_for('log_activity'))

    # Fetch all activity logs for the current user
    logs = activity_collection.find({"user_id": session['user_id']}).sort('timestamp', -1)
    return render_template('log_activity.html', logs=logs)

@app.route('/events', methods=['GET', 'POST'])
def events():
    if 'user_id' not in session:
        flash("Please log in to manage your events.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        event_name = request.form['name']
        description = request.form['description']
        event_date = datetime.strptime(request.form['date'], "%Y-%m-%dT%H:%M")
        reminder_time = datetime.strptime(request.form['reminder_time'], "%Y-%m-%dT%H:%M")
        email = request.form['email']

        event = {
            'user_id': session['user_id'],  # إضافة user_id
            'name': event_name,
            'description': description,
            'date': event_date,
            'reminder_time': reminder_time,
            'email': email
        }
        events_collection.insert_one(event)

        flash("Event added successfully!", "success")
        return redirect(url_for('events'))

    events = events_collection.find({"user_id": session['user_id']}).sort('date', 1)
    return render_template('events.html', events=events)

@app.route('/search', methods=['GET', 'POST'])
def search():
    movie = None
    video_links = []
    if request.method == 'POST':
        movie = request.form.get('movie')  # Retrieve movie name from the form
        if movie:
            video_links = search_youtube(movie)  # Fetch video links using the YouTube API

    return render_template('search.html', movie=movie, video_links=video_links)

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    try:
        if not scheduler.running:
            scheduler.start() 
    except Exception as e:
        print(f"Scheduler already running: {e}")  

    app.run(debug=True, host="0.0.0.0", port=3000) 
