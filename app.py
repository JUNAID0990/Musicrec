from flask import Flask, render_template, request, session, jsonify
from pymongo import MongoClient
import os
import requests
import json
from dotenv import load_dotenv
from bson.objectid import ObjectId

load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"

# MongoDB setup
client = MongoClient(os.getenv("MONGO_URI"))
db = client['music_app']
users_collection = db['users']

# Gemini API setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def call_gemini(prompt):
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    response = requests.post(GEMINI_ENDPOINT, headers=headers, json=data)
    return response.json()

@app.route('/')
def home():
    return render_template('profile.html')

# ---------------- Profile Page ----------------
@app.route('/profile', methods=['POST'])
def profile():
    data = request.get_json()
    user_data = {
        'name': data['name'][:100],
        'age': data['age'],
        'gender': data['gender'],
        'preference': data['preference'],
        'language': data['language'],
        'reference': data['reference'][:100],
        'quiz_answers': []
    }
    # Save user to DB
    result = users_collection.insert_one(user_data)
    user_data['_id'] = str(result.inserted_id)
    session['user'] = user_data
    return jsonify({"success": True, "pid": user_data['_id']})

@app.route('/quiz')
def quiz():
    user_data = session.get('user')
    if not user_data:
        return "User data not found in session", 400

    # Prepare prompt for Gemini to generate quiz questions
    prompt = f"""
    Based on the following user profile:
    - Preference: {user_data.get('preference')}
    - Language: {user_data.get('language')}
    - Reference: {user_data.get('reference')}

    Generate 3 multiple-choice quiz questions to further understand their music taste.
    Return the questions in a JSON list format like this:
    [
        {{"id": 1, "question": "...", "options": ["...", "...", "..."]}},
        ...
    ]
    """

    # Call Gemini API
    response = call_gemini(prompt)

    # Extract and parse questions
    try:
        text_response = response['candidates'][0]['content']['parts'][0]['text']
        cleaned_json = text_response.strip().replace('```json', '').replace('```', '').strip()
        questions = json.loads(cleaned_json)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing questions from Gemini: {e}")
        # Fallback to some default questions if Gemini fails
        questions = [
            {"id": 1, "question": "What's your favorite music genre?", "options": ["Pop", "Rock", "Hip-Hop", "Electronic"]},
            {"id": 2, "question": "Who is your favorite artist?", "options": ["Artist A", "Artist B", "Artist C", "Artist D"]},
            {"id": 3, "question": "What's your mood for music right now?", "options": ["Happy", "Sad", "Energetic", "Calm"]}
        ]

    return render_template('quiz.html', questions=questions)

# ---------------- Quiz API ----------------
@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    data = request.get_json()
    pid = data.get('pid')
    answers = data.get('answers')

    # Find user by pid and update their answers
    user = users_collection.find_one_and_update(
        {'_id': ObjectId(pid)},
        {'$set': {'quiz_answers': answers}},
        return_document=True
    )

    if not user:
        return jsonify({'status': 'error', 'error': 'User not found'}), 404

    # Prepare prompt for Gemini
    rec_prompt = f"""
    Based on the following user profile:
    - Age: {user.get('age')}
    - Gender: {user.get('gender')}
    - Preference: {user.get('preference')}
    - Language: {user.get('language')}
    - Answers: {user.get('quiz_answers')}

    Recommend 5 songs.
    Return the recommendations as a JSON list of objects, where each object has "title" and "artist".
    Example:
    [
        {{"title": "Song Title", "artist": "Artist Name"}},
        ...
    ]
    """
    
    # Call Gemini API
    rec_response = call_gemini(rec_prompt)
    
    # Extract and parse recommendations
    try:
        text_response = rec_response['candidates'][0]['content']['parts'][0]['text']
        # Clean the response by removing markdown and any leading/trailing whitespace
        cleaned_json = text_response.strip().replace('```json', '').replace('```', '').strip()
        recommendations = json.loads(cleaned_json)

        # Add youtube search link to each recommendation
        for rec in recommendations:
            search_query = f"{rec['title']} {rec['artist']}"
            rec['youtube_search_link'] = f"https://www.youtube.com/results?search_query={requests.utils.quote(search_query)}"

    except (KeyError, IndexError, json.JSONDecodeError):
        recommendations = []

    # Save recommendations to user
    users_collection.update_one({'_id': ObjectId(pid)}, {'$set': {'recommendations': recommendations}})

    return jsonify({'status': 'ok'})

@app.route('/result')
def result():
    pid = request.args.get('pid')
    user = users_collection.find_one({'_id': ObjectId(pid)})
    return render_template('result.html', user=user)

# ---------------- Recommendations ----------------
@app.route('/recommendations', methods=['GET'])
def recommendations():
    user_data = session.get('user', {})
    rec_prompt = f"""
    Based on profile: Age {user_data.get('age')}, Gender {user_data.get('gender')}, Preference {user_data.get('preference')}, Language {user_data.get('language')}, 
    and answers: {user_data.get('quiz_answers')}, recommend music or songs in JSON list format.
    """
    rec_response = call_gemini(rec_prompt)
    recommendations = rec_response.get("recommendations", [])
    return jsonify({"recommendations": recommendations})

if __name__ == "__main__":
    app.run(debug=True)
