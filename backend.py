from flask import Flask, render_template, request, jsonify, session, g, redirect
from datetime import datetime, timedelta
import mysql.connector
import hashlib
import os
import json
import serial
import time
import requests

app = Flask(__name__, template_folder=os.path.join("web_portal", "templates"))
app.secret_key = "your-strong-secret-key"




DB_CONFIG = {
    "host": "trolley.proxy.rlwy.net",
    "user": "root",
    "password": "yhIopXkAoldCaBwDsWmyHXfKNpXrVIiH",
    "database": "railway",
    "port": 15988
}


def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
        g.cursor = g.db.cursor(dictionary=True)
    return g.db, g.cursor

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/")
def home():
    return render_template("index.html")


ARDUINO_PORT = 'COM5'  # Your Arduino is on COM5
BAUD_RATE = 9600

# Global variable to track Arduino connection status
arduino = None


def connect_to_arduino():
    """Attempt to connect to the Arduino"""
    global arduino
    try:
        arduino = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to Arduino on {ARDUINO_PORT}")
        time.sleep(2)  # Give Arduino time to reset after connection
        return True
    except Exception as e:
        print(f"Failed to connect to Arduino: {e}")
        arduino = None
        return False


# Try to connect to Arduino when starting the server
connect_to_arduino()


@app.route('/signal_arduino', methods=['POST'])
def signal_arduino():
    try:
        # Replace with your kiosk PC's local IP
        response = requests.post(
            "http://192.168.185.15:5001/signal_arduino",  # 👈 This should match what you saw from Step 2 & 3
            json={"command": "open_door"}
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# Optional: Add diagnostic endpoint to list available COM ports
@app.route('/list_ports', methods=['GET'])
def list_ports():
    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    port_list = [str(p) for p in ports]
    return jsonify({'ports': port_list})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        return register_user()
    return render_template("register.html")

@app.route("/register", methods=["POST"])
def register_user():
    db, cursor = get_db()
    data = request.json

    username = data.get("username")
    role = data.get("role")
    gender = data.get("gender")
    email = data.get("email")
    contact_number = data.get("contact_number")
    school_id = data.get("school_id")
    password = data.get("password")

    # Handle role-based fields correctly
    department = data.get("department") if role == "Teacher" else None
    year_level = data.get("year_level") if role == "Student" else None
    course = data.get("course") if role == "Student" else None

    if not username or not role or not gender or not email or not contact_number or not school_id or not password:
        return jsonify({"message": "All required fields must be filled"}), 400

    if role == "Student" and (not year_level or not course):
        return jsonify({"message": "Student must select a Year Level and Course"}), 400

    if role == "Teacher" and not department:
        return jsonify({"message": "Teacher must select a Department"}), 400

    # Check if user already exists
    cursor.execute("SELECT * FROM users WHERE school_id = %s", (school_id,))
    existing_user = cursor.fetchone()
    if existing_user:
        return jsonify({"message": "User already exists with this School ID."}), 400

    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    cursor.execute("""
        INSERT INTO users (school_id, name, role, gender, email, contact_number, department, password, year_level, course, rfid_number) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
    """, (school_id, username, role, gender, email, contact_number, department, hashed_password, year_level, course))

    db.commit()
    cursor.close()

    return jsonify({"message": "Registration successful! Please proceed to the library front desk to get your RFID card."}), 201

@app.route("/login_manual", methods=["POST"])
def login_manual():
    db, cursor = get_db()
    data = request.json

    if not data:
        return jsonify({"message": "No data received"}), 400

    cursor.execute("SELECT * FROM users WHERE school_id = %s", (data["school_id"],))
    user = cursor.fetchone()
    cursor.close()

    if user:
        hashed_password = hashlib.sha256(data["password"].encode()).hexdigest()
        if hashed_password == user["password"]:
            if user["role"] == "Admin":
                return jsonify({"message": "Admin login successful", "redirect": "/admin_dashboard"})
            else:
                return jsonify({"message": "User login successful", "redirect": "/dashboard"})
        else:
            return jsonify({"message": "Invalid password"}), 401
    else:
        return jsonify({"message": "School ID not found"}), 401

@app.route("/admin_dashboard")
def admin_dashboard():
    db, cursor = get_db()
    cursor.execute("SELECT * FROM books")  # Fetch all books for the admin dashboard
    books = cursor.fetchall()
    print(f"Books in admin dashboard: {books}")  # Debugging line
    cursor.close()
    return render_template("admin_dashboard.html", books=books)

@app.route("/dashboard")
def user_dashboard():
    return render_template("user_dashboard.html")

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/add_book", methods=["POST"])
def add_book():
    db, cursor = get_db()
    data = request.form  # Use request.form to get form data
    title = data.get("title")
    author = data.get("author")
    isbn = data.get("isbn")
    publisher = data.get("publisher")
    publication_date = data.get("publication_date")
    edition = data.get("edition")
    lcc_classification = json.loads(data.get("lcc_classification"))  # Parse the JSON string
    barcode = data.get("barcode")

    # Determine book_type based on lcc_classification
    reserve_categories = [
        "Education", "Science", "Medicine", "Technology", "Law",
        "Fine Arts", "Language and Literature", "Social Sciences", "Political Science"
    ]
    book_type = "Reserve" if any(category in lcc_classification for category in reserve_categories) else "Regular"

    # Check for existing book with the same ISBN
    cursor.execute("SELECT * FROM books WHERE isbn = %s", (isbn,))
    existing_book = cursor.fetchone()
    if existing_book:
        return jsonify({"message": "A book with this ISBN already exists."}), 400

    # Handle image upload
    if 'image' not in request.files:
        return jsonify({"message": "No image file provided"}), 400

    image = request.files['image']
    if image.filename == '':
        return jsonify({"message": "No selected file"}), 400

    # After uploading, ensure the filename is clean
    image_filename = f"{isbn.replace(' ', '').replace('-', '')}.jpg"
    image_path = os.path.join(UPLOAD_FOLDER, image_filename)
    image.save(image_path)  # Save the image

    try:
        # Insert book into database, including the image_url and book_type
        cursor.execute("""
            INSERT INTO books (title, author, isbn, publisher, publication_date, edition, lcc_classification, barcode, status, image_url, book_type) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Available', %s, %s)
        """, (title, author, isbn, publisher, publication_date, edition, ', '.join(lcc_classification), barcode, image_path, book_type))
        db.commit()
        book_id = cursor.lastrowid

        # Create notification for all users (except admins)
        cursor.execute("SELECT id FROM users WHERE role IN ('Student', 'Teacher')")
        users = cursor.fetchall()

        notification_message = f"New book available: {title} by {author}"
        notifications = [(user['id'], notification_message) for user in users]

        # Batch insert notifications for better performance
        cursor.executemany("""
                   INSERT INTO notifications (user_id, message)
                   VALUES (%s, %s)
               """, notifications)

        db.commit()
        return jsonify({"message": "Book added successfully!"}), 201

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 400
    finally:
        cursor.close()

@app.route('/assign_library_card', methods=['POST'])
def assign_library_card():
    db, cursor = get_db()
    data = request.get_json()
    user_id = data['id']
    card_number = data['cardNumber']

    cursor.execute("UPDATE users SET rfid_number = %s WHERE id = %s", (card_number, user_id))
    db.commit()

    if cursor.rowcount > 0:
        return jsonify({'message': 'Library card assigned successfully!'}), 200
    return jsonify({'message': 'User not found!'}), 404

@app.route('/get_unassigned_users', methods=['GET'])
def get_unassigned_users():
    db, cursor = get_db()
    cursor.execute("SELECT * FROM users WHERE rfid_number IS NULL AND role != 'Admin'")
    unassigned_users = cursor.fetchall()
    return jsonify([{
        'id': user['id'],
        'name': user['name'],
        'role': user['role']
    } for user in unassigned_users])

@app.route('/get_users', methods=['GET'])
def get_users():
    user_type = request.args.get('type')
    db, cursor = get_db()

    if user_type == 'teacher':
        cursor.execute("SELECT * FROM users WHERE role = 'Teacher' AND rfid_number IS NOT NULL")
    elif user_type == 'student':
        cursor.execute("SELECT * FROM users WHERE role = 'Student' AND rfid_number IS NOT NULL")
    else:
        return jsonify({"message": "Invalid user type"}), 400

    users = cursor.fetchall()
    return jsonify([{
        'id': user['id'],
        'name': user['name'],
        'role': user['role']
    } for user in users])


@app.route('/get_user_profile')
def get_user_profile():
    user_id = request.args.get('id')
    if not user_id:
        return jsonify({"message": "User ID is required"}), 400

    db, cursor = get_db()
    try:
        # Get basic user info
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"message": "User not found"}), 404

        # Get borrowed books
        cursor.execute("""
            SELECT b.title AS book_title, bb.borrow_date, 
                   bb.return_date, bb.status, bb.payment_status
            FROM borrowed_books bb
            JOIN books b ON bb.book_id = b.id
            WHERE bb.user_id = %s
        """, (user_id,))
        borrowed_books = cursor.fetchall()

        # Get penalty details - UPDATED QUERY
        cursor.execute("""
            SELECT 
                SUM(penalty_amount) as total_penalties,
                SUM(CASE WHEN status = 'Unpaid' THEN penalty_amount ELSE 0 END) as unpaid_penalties
            FROM penalties 
            WHERE user_id = %s
        """, (user_id,))
        penalty_result = cursor.fetchone()

        user_profile = {
            # User info
            "school_id": user["school_id"],
            "name": user["name"],
            "role": user["role"],
            "rfid_number": user["rfid_number"],
            # ... other user fields ...

            # Borrowed books
            "borrowedBooks": [{
                "title": book["book_title"],
                "borrow_date": book["borrow_date"],
                "return_date": book["return_date"],
                "status": book["status"],
                "payment_status": book.get("payment_status", "N/A")
            } for book in borrowed_books],

            # Penalty info - UPDATED FIELDS
            "total_penalties": float(penalty_result["total_penalties"] or 0),
            "unpaid_penalties": float(penalty_result["unpaid_penalties"] or 0)
        }

        return jsonify(user_profile)
    except Exception as e:
        return jsonify({"message": str(e)}), 500
    finally:
        cursor.close()

@app.route('/get_users_user_profile')
def get_users_user_profile():
    school_id = request.args.get('school_id')
    if not school_id:
        return jsonify({"message": "School ID is required"}), 400

    db, cursor = get_db()
    cursor.execute("SELECT * FROM users WHERE school_id = %s", (school_id,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"message": "User not found"}), 404

    user_profile = {
        "school_id": user["school_id"],
        "name": user["name"],
        "role": user["role"],
        "rfid_number": user["rfid_number"],
        "email": user["email"],
        "contact_number": user["contact_number"],
        "gender": user["gender"],
        "year_level": user["year_level"],
        "course": user["course"],
        "department": user["department"],
    }

    return jsonify(user_profile)

@app.route('/profile')
def profile():
    user_id = request.args.get('id')
    return render_template("profile.html", user_id=user_id)

@app.route('/get_borrowed_books', methods=['GET'])
def get_borrowed_books():
    school_id = request.args.get('school_id')
    if not school_id:
        return jsonify({"message": "School ID is required."}), 400

    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT b.title, b.author, bb.borrow_date, bb.due_date, 
                   CASE 
                       WHEN CURDATE() > bb.due_date THEN 
                           CASE 
                               WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                               WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                               ELSE 0 
                           END 
                       ELSE 0 
                   END AS penalty
            FROM borrowed_books bb
            JOIN books b ON bb.book_id = b.id
            JOIN users u ON bb.user_id = u.id
            WHERE u.school_id = %s AND bb.status = 'borrowed'
        """, (school_id,))
        borrowed_books = cursor.fetchall()
        cursor.close()
        return jsonify(borrowed_books)
    except mysql.connector.Error as err:
        print(f"Error loading borrowed books: {err}")
        return jsonify({"message": "Error loading borrowed books"}), 500

@app.route('/mark_penalty_paid', methods=['POST'])
def mark_penalty_paid():
    data = request.get_json()
    user_id = data['userId']
    db, cursor = get_db()

    cursor.execute("UPDATE penalties SET status = 'Paid' WHERE user_id = %s AND status = 'Unpaid'", (user_id,))
    db.commit()

    return jsonify({"message": "Penalty marked as paid!"}), 200

@app.route("/view_books")
def view_books():
    classifications = [
        "General Works (A)",
        "Philosophy Psychology Religion (B)",
        "Auxiliary Sciences of History (C)",
        "World History and History of Europe Asia Africa Australia New Zealand (D)",
        "History of the Americas (E)",
        "Local History of the Americas (F)",
        "Geography, Anthropology, Recreation (G)",
        "Social Sciences (H)",
        "Political Science (J)",
        "Law (K)",
        "Education (L)",
        "Music and Books on Music (M)",
        "Fine Arts (N)",
        "Language and Literature (P)",
        "Science (Q)",
        "Medicine (R)",
        "Agriculture (S)",
        "Technology (T)",
        "Military Science (U)",
        "Naval Science (V)",
        "Bibliography Library Science Information Resources (Z)"
    ]
    return render_template("view_books.html", classifications=classifications)

@app.route('/books/<classification>', methods=['GET'])
def books_by_classification(classification):
    db, cursor = get_db()
    print(f"Fetching books for classification: {classification}")  # Debugging line
    cursor.execute("SELECT * FROM books WHERE lcc_classification LIKE %s", (f'%{classification}%',))
    books = cursor.fetchall()
    print(f"Books found: {books}")  # Debugging line
    cursor.close()
    return jsonify(books)  # Return the books as JSON

@app.route('/get_books', methods=['GET'])
def get_books():
    db, cursor = get_db()
    cursor.execute("SELECT * FROM books")
    books = cursor.fetchall()
    cursor.close()
    return jsonify([{
        'title': book['title'],
        'author': book['author'],
        'isbn': book['isbn'],
        'lcc_classification': book['lcc_classification'].split(', ') if book['lcc_classification'] else [],
        'publisher': book['publisher'],
        'publication_date': book['publication_date'],
        'edition': book['edition'],
        'barcode': book['barcode']
    } for book in books])

@app.route('/book/<int:book_id>', methods=['GET'])
def book_details(book_id):
    db, cursor = get_db()

    # Fetch the book details
    cursor.execute("SELECT * FROM books WHERE id = %s", (book_id,))
    book = cursor.fetchone()

    if not book:
        return jsonify({"message": "Book not found"}), 404

    # Fetch borrowing history
    cursor.execute("""
        SELECT u.name AS borrower_name, b.borrow_date, b.due_date, b.return_date, u.school_id, u.rfid_number, u.role, b.status
        FROM borrowed_books b 
        JOIN users u ON b.user_id = u.id 
        WHERE b.book_id = %s
    """, (book_id,))
    borrow_history = cursor.fetchall()

    # Close the database connection
    cursor.close()
    db.close()

    # Convert book and history to dictionary format
    book_data = {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "isbn": book["isbn"],
        "publisher": book["publisher"],
        "publication_date": book["publication_date"],
        "edition": book["edition"],
        "lcc_classification": book["lcc_classification"],
        "barcode": book["barcode"],
        "book_type": book["book_type"],
        "image_url": book.get("image_url", "/static/default_image_url.jpg"),
        "borrow_history": [
            {
                "borrower_name": record["borrower_name"],
                "school_id": record["school_id"],
                "rfid_number": record["rfid_number"],
                "role": record["role"],
                "borrow_date": record["borrow_date"],
                "due_date": record["due_date"],
                "return_date": record["return_date"],
                "status": record["status"],
            }
            for record in borrow_history
        ]
    }

    # Check if the request is an AJAX request
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(book_data)  # Return JSON for AJAX requests
    else:
        return render_template("book_log.html", book=book_data)  # Render HTML if accessed directly

@app.route('/user/book/<int:book_id>', methods=["GET"])
def book_details_user(book_id):
    db, cursor = get_db()
    try:
        # Fetch book details - ADD book_type TO THE SELECT STATEMENT
        cursor.execute("""
            SELECT b.title, b.author, b.publisher, b.publication_date, b.edition, 
                   b.lcc_classification, b.isbn, b.barcode, b.status, b.image_url, b.book_type
            FROM books b
            WHERE b.id = %s
        """, (book_id,))
        book = cursor.fetchone()

        if not book:
            return jsonify({"message": "Book not found"}), 404

        # Fetch borrowing history for the book
        cursor.execute("""
            SELECT u.name AS borrower_name, u.school_id, u.rfid_number, u.role, 
                   bb.borrow_date, bb.due_date, bb.return_date, bb.status
            FROM borrowed_books bb
            JOIN users u ON bb.user_id = u.id
            WHERE bb.book_id = %s
        """, (book_id,))
        borrow_history = cursor.fetchall()

        # Combine book details and borrowing history
        book_data = {
            "id": book_id,
            "title": book["title"],
            "author": book["author"],
            "publisher": book["publisher"],
            "publication_date": book["publication_date"],
            "edition": book["edition"],
            "lcc_classification": book["lcc_classification"],
            "isbn": book["isbn"],
            "barcode": book["barcode"],
            "status": book["status"],
            "image_url": book["image_url"] or "/static/default_image_url.jpg",
            "book_type": book["book_type"],  # This was missing
            "borrow_history": borrow_history
        }

        return jsonify(book_data)
    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return jsonify({"message": "Database error"}), 500
    finally:
        cursor.close()
@app.route('/track_borrowed_books', methods=['GET'])
def track_borrowed_books():
    db, cursor = get_db()

    # Fetch borrowed books with details including the role of the borrower
    cursor.execute("""
        SELECT b.title, b.isbn, u.name AS borrower_name, u.role, bb.borrow_date 
        FROM borrowed_books bb
        JOIN books b ON bb.book_id = b.id
        JOIN users u ON bb.user_id = u.id
        WHERE bb.status = 'borrowed'
    """)
    borrowed_books = cursor.fetchall()

    return render_template("track_borrowed_books.html", borrowed_books=borrowed_books)

@app.route('/borrowing_rules', methods=['GET'])
def borrowing_rules():
    return render_template("borrowing_rules.html")

@app.route("/search_books", methods=["GET"])
def search_books():
    query = request.args.get('query')
    if not query:
        return jsonify({"message": "Query parameter is required."}), 400

    db, cursor = get_db()
    cursor.execute("""
        SELECT id, title, author, isbn, image_url 
        FROM books 
        WHERE title LIKE %s OR author LIKE %s OR isbn LIKE %s
    """, (f'%{query}%', f'%{query}%', f'%{query}%'))

    books = cursor.fetchall()
    cursor.close()

    return jsonify(books)

@app.route("/get_borrowing_history", methods=["GET"])
def get_borrowing_history():
    # Try to get school_id from query parameter first
    school_id = request.args.get('school_id')

    # If not provided, try to get from session (for kiosk)
    if not school_id and 'user_id' in session:
        db, cursor = get_db()
        cursor.execute("SELECT school_id FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        school_id = user['school_id'] if user else None
        cursor.close()

    if not school_id:
        return jsonify({"message": "School ID is required."}), 400

    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT b.title, b.author, bb.borrow_date, bb.due_date, bb.return_date, 
                   CASE 
                       WHEN bb.return_date > bb.due_date THEN 
                           CASE 
                               WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(bb.return_date, bb.due_date) * 1
                               WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(bb.return_date, bb.due_date) * 3
                               ELSE 0 
                           END
                       WHEN bb.return_date IS NULL AND CURDATE() > bb.due_date THEN
                           CASE 
                               WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                               WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                               ELSE 0 
                           END
                       ELSE 0 
                   END AS late_fees,
                   (SELECT SUM(penalty_amount) FROM penalties WHERE user_id = u.id) AS total_penalties
            FROM borrowed_books bb 
            JOIN books b ON bb.book_id = b.id 
            JOIN users u ON bb.user_id = u.id 
            WHERE u.school_id = %s
            ORDER BY bb.borrow_date DESC
        """, (school_id,))

        borrowing_history = cursor.fetchall()
        return jsonify(borrowing_history)
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route("/get_penalties", methods=["GET"])
def get_penalties():
    school_id = request.args.get('school_id')
    if not school_id:
        return jsonify({"message": "School ID is required."}), 400

    db, cursor = get_db()
    cursor.execute("""
        SELECT b.title, bb.due_date, DATEDIFF(CURDATE(), bb.due_date) AS days_overdue, 
               1 AS daily_fine, 
               DATEDIFF(CURDATE(), bb.due_date) * 1 AS total_fine 
        FROM borrowed_books bb 
        JOIN books b ON bb.book_id = b.id 
        JOIN users u ON bb.user_id = u.id
        WHERE u.school_id = %s AND bb.return_date IS NULL AND CURDATE() > bb.due_date
    """, (school_id,))
    penalties = cursor.fetchall()
    cursor.close()

    return jsonify(penalties)


# Add these new endpoints to your Flask app
@app.route('/get_users_with_fines', methods=['GET'])
def get_users_with_fines():
    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT 
                u.id, 
                u.name, 
                u.rfid_number, 
                u.school_id, 
                u.role, 
                COALESCE(SUM(
                    CASE 
                        WHEN bb.payment_status = 'Unpaid' AND bb.return_date > bb.due_date THEN 
                            CASE 
                                WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(bb.return_date, bb.due_date) * 1
                                WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(bb.return_date, bb.due_date) * 3
                                ELSE 0 
                            END
                        WHEN bb.payment_status = 'Unpaid' AND bb.return_date IS NULL AND CURDATE() > bb.due_date THEN
                            CASE 
                                WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                                WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                                ELSE 0 
                            END
                        ELSE 0 
                    END
                ), 0) AS total_fines
            FROM users u
            LEFT JOIN borrowed_books bb ON u.id = bb.user_id
            LEFT JOIN books b ON bb.book_id = b.id
            WHERE u.role = 'Student'
            GROUP BY u.id
            HAVING total_fines > 0
            ORDER BY total_fines DESC
        """)
        users_with_fines = cursor.fetchall()

        # Convert Decimal to float for JSON serialization
        for user in users_with_fines:
            user['total_fines'] = float(user['total_fines'])

        return jsonify(users_with_fines)
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route('/get_user_fines_details/<int:user_id>', methods=['GET'])
def get_user_fines_details(user_id):
    db, cursor = get_db()
    try:
        # Get user info (without sensitive details)
        cursor.execute("""
            SELECT name, rfid_number, school_id, role 
            FROM users WHERE id = %s
        """, (user_id,))
        user_info = cursor.fetchone()

        if not user_info:
            return jsonify({"message": "User not found"}), 404

        # Get fines details with proper date handling
        cursor.execute("""
            SELECT 
                bb.id as borrow_id,
                b.id as book_id,
                b.title, b.author, b.book_type,
                bb.borrow_date,
                bb.due_date,
                bb.return_date,
                CASE 
                    WHEN bb.return_date > bb.due_date THEN 
                        CASE 
                            WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(bb.return_date, bb.due_date) * 1
                            WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(bb.return_date, bb.due_date) * 3
                            ELSE 0 
                        END
                    WHEN bb.return_date IS NULL AND CURDATE() > bb.due_date THEN
                        CASE 
                            WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                            WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                            ELSE 0 
                        END
                    ELSE 0 
                END AS fine_amount,
                bb.payment_status,
                bb.payment_date
            FROM borrowed_books bb
            JOIN books b ON bb.book_id = b.id
            JOIN users u ON bb.user_id = u.id
            WHERE u.id = %s 
            AND (bb.return_date > bb.due_date OR (bb.return_date IS NULL AND CURDATE() > bb.due_date))
            AND bb.payment_status != 'Paid'
            ORDER BY bb.borrow_date DESC
        """, (user_id,))

        fines_details = []
        for fine in cursor.fetchall():
            # Format dates properly
            formatted_fine = {
                'borrow_id': fine['borrow_id'],
                'book_id': fine['book_id'],
                'title': fine['title'],
                'author': fine['author'],
                'book_type': fine['book_type'],
                'borrow_date': fine['borrow_date'].strftime('%Y-%m-%d') if fine['borrow_date'] else None,
                'due_date': fine['due_date'].strftime('%Y-%m-%d') if fine['due_date'] else None,
                'return_date': fine['return_date'].strftime('%Y-%m-%d') if fine['return_date'] else 'Not returned',
                'fine_amount': float(fine['fine_amount']),
                'payment_status': fine['payment_status'],
                'payment_date': fine['payment_date'].strftime('%Y-%m-%d') if fine['payment_date'] else None
            }
            fines_details.append(formatted_fine)

        # Calculate total fines (only unpaid fines)
        total_fines = sum(float(fine['fine_amount']) for fine in fines_details)

        return jsonify({
            "user_info": {
                "name": user_info["name"],
                "rfid_number": user_info["rfid_number"],
                "school_id": user_info["school_id"],
                "role": user_info["role"]
            },
            "fines_details": fines_details,
            "total_fines": total_fines
        })
    except Exception as e:
        return jsonify({"message": str(e)}), 500
    finally:
        cursor.close()


@app.route('/update_payment_status', methods=['POST'])
def update_payment_status():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data received"}), 400

        required_fields = ['user_id', 'status', 'book_id', 'borrow_id']
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing {field}"}), 400

        db, cursor = get_db()

        # Update payment status in borrowed_books
        cursor.execute("""
            UPDATE borrowed_books 
            SET payment_status = %s, 
                payment_date = CASE WHEN %s = 'Paid' THEN NOW() ELSE NULL END
            WHERE id = %s
        """, (data['status'], data['status'], data['borrow_id']))

        # Update payment status in penalties table
        cursor.execute("""
            UPDATE penalties
            SET status = %s
            WHERE borrowed_book_id = %s
        """, (data['status'], data['borrow_id']))

        # If status is Paid, create a notification
        if data['status'] == 'Paid':
            # Get book and user details
            cursor.execute("""
                SELECT b.title, u.name, u.school_id, p.penalty_amount
                FROM penalties p
                JOIN borrowed_books bb ON p.borrowed_book_id = bb.id
                JOIN books b ON bb.book_id = b.id
                JOIN users u ON p.user_id = u.id
                WHERE p.borrowed_book_id = %s
            """, (data['borrow_id'],))
            details = cursor.fetchone()

            if details:
                message = f"Payment of ₱{details['penalty_amount']:.2f} for '{details['title']}' has been confirmed. Thank you!"

                # Insert notification
                cursor.execute("""
                    INSERT INTO notifications (user_id, message)
                    VALUES (%s, %s)
                """, (data['user_id'], message))

        db.commit()
        return jsonify({"success": True, "message": "Payment status updated successfully"})

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()

@app.route('/mark_fine_paid/<int:user_id>', methods=['POST'])
def mark_fine_paid(user_id):
    db, cursor = get_db()
    try:
        # First, get all unpaid fines for this user
        cursor.execute("""
            SELECT bb.id, b.book_type,
                   CASE 
                       WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                       WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                       ELSE 0 
                   END AS penalty_amount
            FROM borrowed_books bb
            JOIN books b ON bb.book_id = b.id
            JOIN users u ON bb.user_id = u.id
            WHERE u.id = %s 
            AND bb.return_date IS NULL 
            AND CURDATE() > bb.due_date
        """, (user_id,))

        unpaid_fines = cursor.fetchall()

        if not unpaid_fines:
            return jsonify({"message": "No unpaid fines found for this user"}), 404

        # Insert penalty records
        for fine in unpaid_fines:
            cursor.execute("""
                INSERT INTO penalties (user_id, borrowed_book_id, penalty_amount, status, penalty_date)
                VALUES (%s, %s, %s, 'Paid', CURDATE())
            """, (user_id, fine['id'], fine['penalty_amount']))

        db.commit()
        return jsonify({"message": "All fines marked as paid successfully"}), 200
    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route("/get_available_books", methods=["GET"])
def get_available_books():
    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT * FROM books 
            WHERE status IN ('Available', 'Reserved', 'Checked Out')
            ORDER BY 
                CASE 
                    WHEN status = 'Available' THEN 1
                    WHEN status = 'Reserved' THEN 2
                    ELSE 3
                END
        """)
        books = cursor.fetchall()
        return jsonify(books)
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()


# Reservation Routes
@app.route('/reserve_book', methods=['POST'])
def reserve_book():
    db, cursor = get_db()
    data = request.json
    school_id = data.get('school_id')
    book_id = data.get('book_id')

    if not school_id or not book_id:
        return jsonify({"message": "School ID and Book ID are required"}), 400

    try:
        # Get user_id from school_id
        cursor.execute("SELECT id FROM users WHERE school_id = %s", (school_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User not found"}), 404

        # Check if book exists and is available
        cursor.execute("SELECT id, status FROM books WHERE id = %s", (book_id,))
        book = cursor.fetchone()
        if not book:
            return jsonify({"message": "Book not found"}), 404

        if book['status'] not in ['Available', 'Reserved']:
            return jsonify({"message": "Book is not available for reservation"}), 400

        # Check for existing pending reservation
        cursor.execute("""
            SELECT id FROM reservations 
            WHERE user_id = %s AND book_id = %s AND status = 'Pending'
        """, (user['id'], book_id))
        existing_reservation = cursor.fetchone()
        if existing_reservation:
            return jsonify({"message": "You already have a pending reservation for this book"}), 400

        # Create reservation
        reservation_date = datetime.now()
        cursor.execute("""
            INSERT INTO reservations (user_id, book_id, reservation_date, status) 
            VALUES (%s, %s, %s, 'Pending')
        """, (user['id'], book_id, reservation_date))

        # Update book status to Reserved if it was Available
        if book['status'] == 'Available':
            cursor.execute("""
                UPDATE books 
                SET status = 'Reserved' 
                WHERE id = %s
            """, (book_id,))

        db.commit()
        return jsonify({"message": "Book reservation requested successfully!"}), 201

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()


@app.route('/get_user_reservations')
def get_user_reservations():
    school_id = request.args.get('school_id')
    if not school_id:
        return jsonify({"message": "School ID required"}), 400

    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT r.id, b.title, b.author, r.status, r.reservation_date, b.id as book_id
            FROM reservations r
            JOIN books b ON r.book_id = b.id
            JOIN users u ON r.user_id = u.id
            WHERE u.school_id = %s
            ORDER BY r.reservation_date DESC
        """, (school_id,))
        reservations = cursor.fetchall()
        return jsonify(reservations)
    except Exception as e:
        return jsonify({"message": str(e)}), 500
    finally:
        cursor.close()

@app.route('/get_all_reservations', methods=['GET'])
def get_all_reservations():
    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT 
                r.id, 
                u.name as user_name, 
                u.role as user_role,
                u.school_id,
                b.title as book_title, 
                b.author as book_author, 
                r.status, 
                r.reservation_date
            FROM reservations r
            JOIN users u ON r.user_id = u.id
            JOIN books b ON r.book_id = b.id
            ORDER BY r.reservation_date DESC
        """)
        reservations = cursor.fetchall()

        # Convert status to lowercase for consistency
        for res in reservations:
            res['status'] = res['status'].lower() if res['status'] else 'pending'
            if isinstance(res['reservation_date'], datetime):
                res['reservation_date'] = res['reservation_date'].isoformat()

        return jsonify(reservations)
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route('/cancel_reservation', methods=['POST'])
def cancel_reservation():
    db, cursor = get_db()
    data = request.json
    reservation_id = data.get('reservation_id')

    if not reservation_id:
        return jsonify({"message": "Reservation ID is required"}), 400

    try:
        # Verify reservation exists and is pending
        cursor.execute("""
            SELECT r.id, r.book_id, b.status as book_status
            FROM reservations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.status = 'Pending'
        """, (reservation_id,))
        reservation = cursor.fetchone()
        if not reservation:
            return jsonify({"message": "Pending reservation not found or already processed"}), 404

        # Delete reservation
        cursor.execute("DELETE FROM reservations WHERE id = %s", (reservation_id,))

        # Check if there are other reservations for this book
        cursor.execute("""
            SELECT COUNT(*) as reservation_count
            FROM reservations
            WHERE book_id = %s AND status = 'Approved'
        """, (reservation['book_id'],))
        other_reservations = cursor.fetchone()

        # Update book status back to Available if no other reservations exist
        if reservation['book_status'] == 'Reserved' and other_reservations['reservation_count'] == 0:
            cursor.execute("""
                UPDATE books 
                SET status = 'Available' 
                WHERE id = %s
            """, (reservation['book_id'],))

        db.commit()
        return jsonify({"message": "Reservation cancelled successfully"}), 200

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()


@app.route('/update_reservation_status', methods=['POST'])
def update_reservation_status():
    db, cursor = get_db()
    data = request.json
    reservation_id = data.get('reservation_id')
    status = data.get('status')

    if not reservation_id or not status:
        return jsonify({"message": "Reservation ID and status are required"}), 400

    if status.lower() not in ['approved', 'rejected']:
        return jsonify({"message": "Invalid status"}), 400

    try:
        # Verify reservation exists and is pending
        cursor.execute("""
            SELECT r.id, r.user_id, r.book_id, b.title, b.status as book_status
            FROM reservations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.status = 'pending'
        """, (reservation_id,))
        reservation = cursor.fetchone()
        if not reservation:
            return jsonify({"message": "Pending reservation not found or already processed"}), 404

        # Update reservation status
        cursor.execute("""
            UPDATE reservations 
            SET status = %s 
            WHERE id = %s
        """, (status, reservation_id))

        # Create notification for user
        message = f"Your reservation for '{reservation['title']}' has been {status.lower()}. " + \
                 ("Please visit the library front desk to borrow the book." if status.lower() == 'approved' else "")
        cursor.execute("""
            INSERT INTO notifications (user_id, message)
            VALUES (%s, %s)
        """, (reservation['user_id'], message))

        # If approved, update book status to Reserved
        if status.lower() == 'approved':
            cursor.execute("""
                UPDATE books 
                SET status = 'Reserved' 
                WHERE id = %s
            """, (reservation['book_id'],))

        db.commit()
        return jsonify({"message": f"Reservation {status.lower()} successfully"}), 200

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()


# Get penalties with details(User Dashboard)
@app.route('/get_penalties_details', methods=['GET'])
def get_penalties_details():
    school_id = request.args.get('school_id')
    if not school_id:
        return jsonify({"message": "School ID is required"}), 400

    db, cursor = get_db()
    try:
        # Get user ID
        cursor.execute("SELECT id FROM users WHERE school_id = %s", (school_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User not found"}), 404

        # Get penalties with book titles, checking both tables
        cursor.execute("""
            SELECT 
                b.title,
                p.penalty_amount,
                COALESCE(bb.payment_status, p.status) as status,
                DATEDIFF(p.created_at, bb.due_date) AS days_late
            FROM penalties p
            JOIN borrowed_books bb ON p.borrowed_book_id = bb.id
            JOIN books b ON bb.book_id = b.id
            WHERE p.user_id = %s
            ORDER BY p.created_at DESC
        """, (user['id'],))

        penalties = cursor.fetchall()

        # Calculate totals - only count unpaid penalties
        total = sum(float(p['penalty_amount']) for p in penalties if p['status'] == 'Unpaid')
        unpaid = sum(float(p['penalty_amount']) for p in penalties if p['status'] == 'Unpaid')

        return jsonify({
            "penalties": penalties,
            "total_penalties": total,
            "unpaid_penalties": unpaid
        })

    except Exception as e:
        return jsonify({"message": str(e)}), 500
    finally:
        cursor.close()

# Backend API endpoints for notifications - Flask example
# Include these in your Flask application
@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    try:
        # Get school_id from query parameters for kiosk
        school_id = request.args.get('school_id')
        notification_type = request.args.get('type')

        if not school_id:
            return jsonify({"message": "School ID is required"}), 400

        db, cursor = get_db()

        # First get user_id from school_id
        cursor.execute("SELECT id FROM users WHERE school_id = %s", (school_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"message": "User not found"}), 404

        # Base query
        query = """
            SELECT id, message, created_at, is_read 
            FROM notifications 
            WHERE user_id = %s
        """

        # Add type filter if specified
        params = [user['id']]
        if notification_type == 'payment':
            query += " AND (message LIKE %s OR message LIKE %s)"
            params.extend(['%payment%', '%Thank you for settling%'])

        query += " ORDER BY created_at DESC LIMIT 50"

        cursor.execute(query, params)
        notifications = cursor.fetchall()

        # Convert datetime objects to strings for JSON serialization
        for notification in notifications:
            if isinstance(notification['created_at'], datetime):
                notification['created_at'] = notification['created_at'].isoformat()

        return jsonify({"notifications": notifications}), 200

    except Exception as e:
        print(f"Error in get_notifications: {str(e)}")
        return jsonify({"message": "An error occurred while fetching notifications"}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()


@app.route('/api/notifications/unread/count', methods=['GET'])
def get_unread_count():
    try:
        # Get school_id from query parameters for kiosk
        school_id = request.args.get('school_id')

        if not school_id:
            return jsonify({"message": "School ID is required"}), 400

        db, cursor = get_db()

        # First get user_id from school_id
        cursor.execute("SELECT id FROM users WHERE school_id = %s", (school_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"message": "User not found"}), 404

        cursor.execute("""
            SELECT COUNT(*) as unread_count
            FROM notifications 
            WHERE user_id = %s AND is_read = FALSE
        """, (user['id'],))

        result = cursor.fetchone()
        return jsonify({"unread_count": result['unread_count']}), 200

    except Exception as e:
        print(f"Error in get_unread_count: {str(e)}")
        return jsonify({"message": "An error occurred while fetching notification count"}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()


@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
def mark_notification_read(notification_id):
    try:
        school_id = request.args.get('school_id')
        if not school_id:
            return jsonify({"error": "school_id required"}), 400

        db, cursor = get_db()

        # Verify the notification belongs to this user
        cursor.execute("""
            UPDATE notifications n
            JOIN users u ON n.user_id = u.id
            SET n.is_read = TRUE 
            WHERE n.id = %s AND u.school_id = %s
        """, (notification_id, school_id))

        db.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"Error in mark_notification_read: {str(e)}")
        return jsonify({"error": "An error occurred while marking notification as read"}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()


@app.route('/remove_user', methods=['POST'])
def remove_user():
    try:
        data = request.get_json()
        user_id = data.get('id')

        if not user_id:
            return jsonify({"message": "User ID is required"}), 400

        db, cursor = get_db()

        # First check if user has borrowed books
        cursor.execute("SELECT COUNT(*) as count FROM borrowed_books WHERE user_id = %s AND status = 'borrowed'",
                       (user_id,))
        borrowed_count = cursor.fetchone()['count']

        if borrowed_count > 0:
            return jsonify({"message": "Cannot remove user with borrowed books"}), 400

        # Delete user
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"message": "User not found"}), 404

        return jsonify({"message": "User removed successfully"}), 200

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()


@app.route('/borrow_reserved_book', methods=['POST'])
def borrow_reserved_book():
    try:
        data = request.get_json()
        book_id = data.get('book_id')
        reservation_id = data.get('reservation_id')

        # Verify the reservation exists and is approved
        cursor.execute("""
            SELECT r.id, r.user_id, r.book_id, b.title, b.book_type
            FROM reservations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.status = 'Approved'
        """, (reservation_id,))
        reservation = cursor.fetchone()

        if not reservation:
            return jsonify({"success": False, "message": "No approved reservation found"}), 404

        # Get user details
        cursor.execute("SELECT id, role FROM users WHERE id = %s", (reservation['user_id'],))
        user = cursor.fetchone()

        # Calculate loan period
        if user['role'] == 'Student':
            loan_period = 1 if reservation['book_type'] == 'Reserve' else 7
        elif user['role'] == 'Teacher':
            loan_period = 152  # 5 months
        else:
            loan_period = 7  # Default

        borrow_date = datetime.now()
        due_date = borrow_date + timedelta(days=loan_period)

        # Create borrowing record
        cursor.execute("""
            INSERT INTO borrowed_books 
            (user_id, book_id, borrow_date, due_date, status) 
            VALUES (%s, %s, %s, %s, 'borrowed')
        """, (user['id'], book_id, borrow_date, due_date))

        # Update book status
        cursor.execute("""
            UPDATE books SET status = 'Borrowed' WHERE id = %s
        """, (book_id,))

        # Update reservation status
        cursor.execute("""
            UPDATE reservations SET status = 'Completed' WHERE id = %s
        """, (reservation_id,))

        db.commit()

        # Prepare receipt data
        receipt_data = {
            "book_title": reservation['title'],
            "book_author": "Unknown",  # You should fetch this
            "borrower_name": "User Name",  # Fetch this
            "school_id": "12345",  # Fetch this
            "borrow_date": borrow_date.strftime("%Y-%m-%d %H:%M"),
            "due_date": due_date.strftime("%Y-%m-%d %H:%M"),
            "book_type": reservation['book_type']
        }

        return jsonify({
            "success": True,
            "message": "Reserved book borrowed successfully",
            "receipt_data": receipt_data
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/verify_reserved_book')
def verify_reserved_book():
    book_id = request.args.get('book_id')
    barcode = request.args.get('barcode')

    # Verify the barcode matches the book
    db, cursor = get_db()
    cursor.execute("SELECT barcode FROM books WHERE id = %s", (book_id,))
    book = cursor.fetchone()

    if not book:
        return jsonify({"valid": False, "message": "Book not found"})

    return jsonify({
        "valid": book['barcode'] == barcode,
        "book_title": book.get('title', '')
    })


@app.route('/complete_reserved_borrow', methods=['POST'])
def complete_reserved_borrow():
    data = request.json
    book_id = data['book_id']
    reservation_id = data['reservation_id']
    barcode = data['barcode']

    db, cursor = get_db()

    try:
        # 1. Verify reservation is still valid
        cursor.execute("""
            SELECT r.user_id, b.title, b.book_type
            FROM reservations r
            JOIN books b ON r.book_id = b.id
            WHERE r.id = %s AND r.status = 'Approved'
        """, (reservation_id,))
        reservation = cursor.fetchone()

        if not reservation:
            return jsonify({"success": False, "message": "Reservation no longer valid"})

        # 2. Create borrowing record (similar to regular borrowing)
        borrow_date = datetime.now()
        if reservation['book_type'] == 'Reserve':
            due_date = borrow_date + timedelta(days=1)  # 1 day for reserve books
        else:
            due_date = borrow_date + timedelta(days=7)  # 1 week for regular books

        cursor.execute("""
            INSERT INTO borrowed_books 
            (user_id, book_id, borrow_date, due_date, status) 
            VALUES (%s, %s, %s, %s, 'borrowed')
        """, (reservation['user_id'], book_id, borrow_date, due_date))

        # 3. Update book status
        cursor.execute("""
            UPDATE books SET status = 'Checked Out' WHERE id = %s
        """, (book_id,))

        # 4. Update reservation status
        cursor.execute("""
            UPDATE reservations SET status = 'Completed' WHERE id = %s
        """, (reservation_id,))

        db.commit()

        # 5. Prepare receipt data
        receipt_data = {
            "book_title": reservation['title'],
            "borrow_date": borrow_date.strftime("%Y-%m-%d %H:%M"),
            "due_date": due_date.strftime("%Y-%m-%d %H:%M"),
            "book_type": reservation['book_type']
        }

        return jsonify({
            "success": True,
            "message": "Book borrowed successfully",
            "receipt_data": receipt_data
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# Kiosk Part
@app.route("/rfid_login", methods=["POST"])
def rfid_login():
    db, cursor = get_db()
    data = request.json
    rfid_number = data.get("rfid").strip()[:10]  # Trim and ensure 10-digit format

    print(f"Received RFID from scanner: '{rfid_number}' (Length: {len(rfid_number)})")  # Debugging log

    # Include 'rfid_number' in the SELECT statement
    cursor.execute("SELECT id, name, role, rfid_number FROM users WHERE rfid_number = %s", (rfid_number,))
    user = cursor.fetchone()

    if user:
        print(f"Match Found in DB -> Name: {user['name']}, Stored RFID: '{user['rfid_number']}'")
        session["user_id"] = user["id"]
        return jsonify({"success": True, "redirect": "/kiosk_dashboard", "user_id": user["id"], "name": user["name"], "role": user["role"]})
    else:
        print("RFID not found in database!")
        return jsonify({"success": False, "message": "Access Denied"}), 401

@app.route("/kiosk")
def kiosk():
    return render_template("kioskma.html")  # Ensure the file exists in templates/

@app.route("/kiosk_dashboard")
def kiosk_dashboard():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401  # Ensure session security

    return render_template("kiosk_dashboard.html")

@app.route("/kiosk_search_books", methods=["GET"])
def kiosk_search_books():
    query = request.args.get('query')
    if not query:
        return jsonify({"message": "Query parameter is required."}), 400

    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT id, title, author, isbn, image_url, status, book_type
            FROM books 
            WHERE (title LIKE %s OR author LIKE %s OR isbn LIKE %s)
            AND status IN ('Available', 'Reserved', 'Checked Out')
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))

        books = cursor.fetchall()
        return jsonify(books)
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route("/get_kiosk_user_profile")
def get_kiosk_user_profile():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    db, cursor = get_db()
    cursor.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
    user = cursor.fetchone()

    if not user:
        return jsonify({"message": "User not found"}), 404

    user_profile = {
        "id": user["id"],
          "school_id": user["school_id"],
        "name": user["name"],
        "role": user["role"],
        "rfid_number": user["rfid_number"],
        "email": user["email"],
        "contact_number": user["contact_number"],
        "gender": user["gender"],
        "year_level": user["year_level"],
        "course": user["course"],
        "department": user["department"],

    }

    return jsonify(user_profile)

@app.route('/borrow_book', methods=['POST'])
def borrow_book():
    if "user_id" not in session:
        return jsonify({"message": "User  not logged in."}), 401

    data = request.json
    book_id = data.get('book_id')

    if not book_id:
        return jsonify({"message": "Book ID is required."}), 400

    db, cursor = get_db()
    user_id = session["user_id"]

    try:
        # Start a transaction
        cursor.execute("START TRANSACTION")

        # Check if the book is available
        cursor.execute("SELECT status FROM books WHERE id = %s FOR UPDATE", (book_id,))
        book = cursor.fetchone()

        if not book:
            return jsonify({"message": "Book not found."}), 404

        # Log the book status for debugging
        print(f"Book ID: {book_id}, Status: {book['status']}")  # Debugging line

        if book["status"] != "Available":
            return jsonify({"message": "This book is already borrowed by another user."}), 400

        # Proceed with borrowing logic...
        # Fetch user role
        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User  not found."}), 404

        user_role = user['role']

        # Fetch book type
        cursor.execute("SELECT book_type FROM books WHERE id = %s", (book_id,))
        book = cursor.fetchone()
        if not book:
            return jsonify({"message": "Book not found."}), 404

        book_type = book['book_type']

        # Determine loan period based on user role and book type
        if user_role == 'Student':
            if book_type == 'Reserve':
                loan_period_days = 1   # Reserve books: 1 day
            else:
                loan_period_days = 7  # Regular books: 7 days
        elif user_role == 'Teacher':
            loan_period_days = 152  # Teacher: 152 days (5 months)
        else:
            loan_period_days = 7  # Default to 7 days for other roles

        # Get the current date and calculate the due date
        borrow_date = datetime.now()
        due_date = borrow_date + timedelta(days=loan_period_days)

        # Insert the borrowing record into the database
        cursor.execute("""
            INSERT INTO borrowed_books (user_id, book_id, borrow_date, due_date, status) 
            VALUES (%s, %s, %s, %s, 'borrowed')
        """, (user_id, book_id, borrow_date, due_date))

        # Update the book status to 'Borrowed'
        cursor.execute("""
            UPDATE books 
            SET status = 'Borrowed' 
            WHERE id = %s
        """, (book_id,))

        # Commit the transaction
        db.commit()

        return jsonify({"message": "Book borrowing confirmed!", "due_date": due_date.strftime("%Y-%m-%d")}), 201
    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"message": str(err)}), 400
    finally:
        cursor.close()

@app.route('/get_book_by_barcode', methods=['GET'])
def get_book_by_barcode():
    barcode = request.args.get('barcode')
    if not barcode:
        return jsonify({"message": "Barcode is required."}), 400

    # More robust cleaning - remove ALL non-digit characters
    cleaned_barcode = ''.join(c for c in barcode if c.isdigit())
    print(f"Original barcode: {barcode}, Cleaned: {cleaned_barcode}")  # Debugging

    db, cursor = get_db()
    cursor.execute("SELECT * FROM books WHERE barcode = %s", (cleaned_barcode,))
    book = cursor.fetchone()

    if not book:
        return jsonify({"message": "No book found in the system."}), 404

    return jsonify({
        'id': book['id'],
        'title': book['title'],
        'author': book['author'],
        'isbn': book['isbn'],
        'publisher': book['publisher'],
        'publication_date': book['publication_date'],
        'edition': book['edition'],
        'barcode': book['barcode'],
        'image_url': book['image_url'],
        'book_type': book['book_type'],
        'lcc_classification': book['lcc_classification']
    })

@app.route('/return_book', methods=['POST'])
def return_book():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.json
    book_id = data.get('book_id')

    if not book_id:
        return jsonify({"message": "Book ID is required."}), 400

    db, cursor = get_db()
    user_id = session["user_id"]

    try:
        # Start transaction
        cursor.execute("START TRANSACTION")

        # 1. Get the active borrowing record with book type
        cursor.execute("""
            SELECT bb.id, bb.borrow_date, bb.due_date, b.book_type, bb.status
            FROM borrowed_books bb
            JOIN books b ON bb.book_id = b.id
            WHERE bb.book_id = %s 
            AND bb.user_id = %s 
            AND bb.status = 'borrowed'
            ORDER BY bb.borrow_date DESC
            LIMIT 1 FOR UPDATE
        """, (book_id, user_id))
        borrowing = cursor.fetchone()

        if not borrowing:
            return jsonify({
                "message": "No active borrowing record found.",
                "success": False
            }), 404

        # 2. Calculate penalty if late
        return_date = datetime.now()
        is_late = return_date > borrowing['due_date']
        penalty = 0
        status = 'Paid'  # Default status

        if is_late:
            cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

            if user['role'] == 'Student':
                days_late = (return_date - borrowing['due_date']).days
                penalty = days_late * (3 if borrowing['book_type'] == 'Reserve' else 1)
                status = 'Unpaid'

        # 3. Update borrowing record
        cursor.execute("""
            UPDATE borrowed_books 
            SET return_date = %s, 
                status = 'returned',
                penalty_amount = %s,
                payment_status = %s
            WHERE id = %s
        """, (return_date, penalty, status, borrowing['id']))

        # 4. Check if there are pending reservations for this book
        cursor.execute("""
            SELECT COUNT(*) as reservation_count
            FROM reservations
            WHERE book_id = %s AND status = 'Approved'
        """, (book_id,))
        reservation_count = cursor.fetchone()['reservation_count']

        # 5. Update book status based on reservations
        if reservation_count > 0:
            new_status = 'Reserved'
        else:
            new_status = 'Available'

        cursor.execute("""
            UPDATE books 
            SET status = %s 
            WHERE id = %s
        """, (new_status, book_id))

        # 6. Handle penalty record
        if penalty > 0:
            # Check if pending penalty exists
            cursor.execute("""
                SELECT id FROM penalties 
                WHERE borrowed_book_id = %s AND status = 'Pending'
            """, (borrowing['id'],))
            existing_penalty = cursor.fetchone()

            if existing_penalty:
                # Update pending penalty to Unpaid
                cursor.execute("""
                    UPDATE penalties 
                    SET penalty_amount = %s,
                        status = 'Unpaid',
                        created_at = %s
                    WHERE id = %s
                """, (penalty, return_date, existing_penalty['id']))
            else:
                # Create new penalty record
                cursor.execute("""
                    INSERT INTO penalties 
                    (user_id, borrowed_book_id, penalty_amount, status, created_at) 
                    VALUES (%s, %s, %s, 'Unpaid', %s)
                """, (user_id, borrowing['id'], penalty, return_date))

        # 7. Commit transaction
        db.commit()

        # 8. Prepare receipt data
        cursor.execute("""
            SELECT b.title, b.author, b.isbn, b.barcode, b.book_type,
                   u.name, u.school_id, u.rfid_number, u.role
            FROM books b
            JOIN users u ON u.id = %s
            WHERE b.id = %s
        """, (user_id, book_id))
        receipt_data = cursor.fetchone()

        return jsonify({
            "message": "Book returned successfully!",
            "success": True,
            "receipt_data": {
                "book_title": receipt_data['title'],
                "book_author": receipt_data['author'],
                "book_isbn": receipt_data['isbn'],
                "book_barcode": receipt_data['barcode'],
                "book_type": receipt_data['book_type'],
                "borrower_name": receipt_data['name'],
                "school_id": receipt_data['school_id'],
                "rfid_number": receipt_data['rfid_number'],
                "role": receipt_data['role'],
                "borrow_date": borrowing['borrow_date'].strftime('%Y-%m-%d %H:%M'),
                "due_date": borrowing['due_date'].strftime('%Y-%m-%d %H:%M'),
                "return_date": return_date.strftime('%Y-%m-%d %H:%M'),
                "penalty": penalty,
                "status": status
            }
        }), 200

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({
            "message": f"Database error: {str(err)}",
            "success": False
        }), 500
    except Exception as e:
        db.rollback()
        return jsonify({
            "message": f"Unexpected error: {str(e)}",
            "success": False
        }), 500
    finally:
        cursor.close()

@app.route('/get_unreturned_books', methods=['GET'])
def get_unreturned_books():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    db, cursor = get_db()
    cursor.execute("""
        SELECT b.id, b.title, b.author, b.isbn, b.barcode, bb.borrow_date, bb.due_date, 
               CASE 
                   WHEN CURDATE() > bb.due_date THEN 
                       CASE 
                           WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                           WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                           ELSE 0 
                       END 
                   ELSE 0 
               END AS penalty
        FROM borrowed_books bb
        JOIN books b ON bb.book_id = b.id
        JOIN users u ON bb.user_id = u.id
        WHERE bb.user_id = %s AND bb.status = 'borrowed'
    """, (session["user_id"],))
    unreturned_books = cursor.fetchall()
    cursor.close()

    return jsonify(unreturned_books)


@app.route('/get_return_details/<int:book_id>', methods=['GET'])
def get_return_details(book_id):
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    db, cursor = get_db()
    cursor.execute("""
        SELECT b.title as book_title, b.author as book_author, b.isbn as book_isbn, b.lcc_classification,
               u.name as borrower_name, u.rfid_number, u.school_id, u.role,
               bb.borrow_date, bb.due_date, b.book_type, b.barcode,
               CASE 
                   WHEN CURDATE() > bb.due_date THEN 
                       CASE 
                           WHEN u.role = 'Student' AND b.book_type = 'Regular' THEN DATEDIFF(CURDATE(), bb.due_date) * 1
                           WHEN u.role = 'Student' AND b.book_type = 'Reserve' THEN DATEDIFF(CURDATE(), bb.due_date) * 3
                           ELSE 0 
                       END 
                   ELSE 0 
               END AS penalty
        FROM borrowed_books bb
        JOIN books b ON bb.book_id = b.id
        JOIN users u ON bb.user_id = u.id
        WHERE bb.book_id = %s AND bb.user_id = %s AND bb.status = 'borrowed'
        ORDER BY bb.borrow_date DESC LIMIT 1
    """, (book_id, session["user_id"]))
    return_details = cursor.fetchone()
    cursor.close()
    return jsonify(return_details)


@app.route('/confirm_borrow', methods=['POST'])
def confirm_borrow():
    if "user_id" not in session:
        return jsonify({"message": "User not logged in."}), 401

    data = request.json
    book_id = data.get('book_id')

    if not book_id:
        return jsonify({"message": "Book ID is required."}), 400

    db, cursor = get_db()
    user_id = session["user_id"]

    try:
        # Start transaction
        cursor.execute("START TRANSACTION")

        # 1. Check if book exists and is available or reserved for this user
        cursor.execute("""
            SELECT b.id, b.status, b.book_type 
            FROM books b
            WHERE b.id = %s FOR UPDATE
        """, (book_id,))
        book = cursor.fetchone()

        if not book:
            return jsonify({"message": "Book not found.", "success": False}), 404

        # Check if book is reserved for this user
        if book['status'] == 'Reserved':
            cursor.execute("""
                SELECT id FROM reservations 
                WHERE user_id = %s AND book_id = %s AND status = 'Approved'
            """, (user_id, book_id))
            reservation = cursor.fetchone()

            if not reservation:
                return jsonify({
                    "message": "This book is reserved for another user.",
                    "success": False
                }), 400

        elif book['status'] != 'Available':
            return jsonify({
                "message": "Book is not available for borrowing.",
                "success": False
            }), 400

        # 2. Get user details and check borrowing limit
        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User not found.", "success": False}), 404

        cursor.execute("""
            SELECT COUNT(*) as current_count 
            FROM borrowed_books 
            WHERE user_id = %s AND status = 'borrowed'
        """, (user_id,))
        borrow_count = cursor.fetchone()['current_count']

        max_allowed = 5 if user['role'] == 'Teacher' else 3  # Students:3, Teachers:5

        if borrow_count >= max_allowed:
            return jsonify({
                "message": f"You've reached your borrowing limit ({max_allowed} books). Please return books first.",
                "success": False,
                "limit_reached": True
            }), 400

        # 3. Calculate loan period
        if user['role'] == 'Student':
            loan_period = 1 if book['book_type'] == 'Reserve' else 7
        elif user['role'] == 'Teacher':
            loan_period = 152  # 5 months for Teacher
        else:
            loan_period = 7  # Default for other roles

        # 4. Create borrowing record
        borrow_date = datetime.now()
        due_date = borrow_date + timedelta(days=loan_period)

        cursor.execute("""
            INSERT INTO borrowed_books 
            (user_id, book_id, borrow_date, due_date, status, payment_status) 
            VALUES (%s, %s, %s, %s, 'borrowed', 'Unpaid')
        """, (user_id, book_id, borrow_date, due_date))

        # 5. Update book status to Borrowed
        cursor.execute("""
            UPDATE books 
            SET status = 'Checked Out' 
            WHERE id = %s
        """, (book_id,))

        # 6. If this was a reserved book, update the reservation status
        if book['status'] == 'Reserved':
            cursor.execute("""
                UPDATE reservations 
                SET status = 'Completed' 
                WHERE user_id = %s AND book_id = %s AND status = 'Approved'
            """, (user_id, book_id))

        # 7. Commit transaction
        db.commit()

        # 8. Prepare receipt data
        cursor.execute("""
            SELECT b.title, b.author, b.isbn, b.barcode, b.book_type, b.lcc_classification,
                   u.name, u.school_id, u.rfid_number, u.role
            FROM books b
            JOIN users u ON u.id = %s
            WHERE b.id = %s
        """, (user_id, book_id))
        receipt_data = cursor.fetchone()

        return jsonify({
            "message": "Book borrowing confirmed!",
            "success": True,
            "due_date": due_date.strftime("%Y-%m-%d %H:%M:%S"),
            "receipt_data": {
                "book_title": receipt_data['title'],
                "book_author": receipt_data['author'],
                "book_isbn": receipt_data['isbn'],
                "book_barcode": receipt_data['barcode'],
                "book_type": receipt_data['book_type'],
                "book_category": receipt_data['lcc_classification'],
                "borrower_name": receipt_data['name'],
                "school_id": receipt_data['school_id'],
                "rfid_number": receipt_data['rfid_number'],
                "role": receipt_data['role'],
                "borrow_date": borrow_date.strftime("%Y-%m-%d %H:%M:%S"),
                "due_date": due_date.strftime("%Y-%m-%d %H:%M:%S"),
                "penalty": 0
            }
        }), 201

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({
            "message": f"Database error: {str(err)}",
            "success": False,
            "error_type": "database"
        }), 500
    except Exception as e:
        db.rollback()
        return jsonify({
            "message": f"Unexpected error: {str(e)}",
            "success": False,
            "error_type": "general"
        }), 500
    finally:
        cursor.close()


@app.route('/check_unpaid_penalties', methods=['GET'])
def check_unpaid_penalties():
    if "user_id" not in session:
        return jsonify({"message": "Unauthorized"}), 401

    db, cursor = get_db()
    user_id = session["user_id"]

    try:
        # Check for unpaid penalties
        cursor.execute("""
            SELECT SUM(penalty_amount) as total_unpaid
            FROM penalties
            WHERE user_id = %s AND status = 'Unpaid'
        """, (user_id,))
        penalty_result = cursor.fetchone()
        total_unpaid = penalty_result['total_unpaid'] if penalty_result['total_unpaid'] else 0

        if total_unpaid > 0:
            return jsonify({
                "has_unpaid_penalties": True,
                "total_unpaid": float(total_unpaid),
                "message": f"You have ₱{total_unpaid:.2f} in unpaid penalties. Please settle them to borrow books."
            })

        return jsonify({
            "has_unpaid_penalties": False,
            "total_unpaid": 0,
            "message": "No unpaid penalties found"
        })

    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()

@app.route('/get_current_borrow_count', methods=['GET'])
def get_current_borrow_count():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"message": "User ID is required"}), 400

    db, cursor = get_db()
    try:
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM borrowed_books 
            WHERE user_id = %s AND status = 'borrowed'
        """, (user_id,))
        result = cursor.fetchone()
        return jsonify({"count": result['count']})
    except mysql.connector.Error as err:
        return jsonify({"message": str(err)}), 500
    finally:
        cursor.close()



@app.route('/logout', methods=['POST'])
def logout():
    session.clear()  # Clear the session
    return jsonify({"message": "Logged out successfully."}), 200

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=10000)
