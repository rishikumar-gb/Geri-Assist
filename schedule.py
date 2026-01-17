from supabase import create_client, Client
from flask import Flask, jsonify, request, session
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import timedelta, datetime
from datetime import date
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import calendar
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json
import asyncio
import jwt

app_notif = FastAPI()

active_connections = {}  # emp_id -> WebSocket


app = Flask(__name__)
app.secret_key = 'seckey257'
CORS(app)

# Replace with your values
url = "https://asbfhxdomvclwsrekdxi.supabase.co"
# key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFzYmZoeGRvbXZjbHdzcmVrZHhpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTQzMjI3OTUsImV4cCI6MjA2OTg5ODc5NX0.0VzbWIc-uxIDhI03g04n8HSPRQ_p01UTJQ1sg8ggigU"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFzYmZoeGRvbXZjbHdzcmVrZHhpIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NDMyMjc5NSwiZXhwIjoyMDY5ODk4Nzk1fQ.iPXQg3KBXGXNlJwMzv5Novm0Qnc7Y5sPNE4RYxg3wqI"
supabase: Client = create_client(url, key)
app.config['SECRET_KEY'] = 'gerri-session-secret-2026'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
Session(app)
CORS(app, supports_credentials=True)


# schedule display
@app.route('/scheduled', methods=['GET'])
def schedule():
    clients = supabase.table("client").select("*").execute()
    employees = supabase.table("employee").select("*").execute()
    shifts = supabase.table("shift").select("*").execute()
    daily_shifts = supabase.table("daily_shift").select("*").execute()

    datatosend = {
        "client": clients.data,
        "employee": employees.data,
        "shift": shifts.data,
        "daily_shift": daily_shifts.data
    }
    return jsonify(datatosend)

@app.route('/submit', methods=['POST'])
def edit_schedule():
    data = request.json
    s_id = data['shift_id']

    # 1. Fetch client
    client = supabase.table("client").select("*").eq("client_id", data['client_id']).execute()

    s_time = datetime.strptime(data['shift_start_time'], "%Y-%m-%dT%H:%M:%S")
    e_time = datetime.strptime(data['shift_end_time'], "%Y-%m-%dT%H:%M:%S")

    # 2. Update shift times
    supabase.table("shift").update({
        "shift_start_time": str(s_time),
        "shift_end_time": str(e_time)
    }).eq("shift_id", s_id).execute()

    # 3. Call Postgres function for daily_shift updates
    supabase.rpc("update_daily_shifts", {}).execute()

    # 4. Fetch updated shift
    updated_shift = supabase.table("shift").select("*").eq("client_id", data['client_id']).eq("shift_id", data['shift_id']).execute()

    print("Updated shift:", updated_shift.data)
    emp_id = updated_shift.data[0]['emp_id']
    print(f"Rescheduled Shift Assigned to employee {emp_id}:", f"Shift Re-scheduled for client id: {data['client_id']} - from {updated_shift.data[0]['shift_start_time']} to {updated_shift.data[0]['shift_end_time']}. Time of reschedule: {datetime.now()}. Do you accept or reject the offer.")
    #tokens = supabase.table("employee_tokens").select("fcm_token").eq("emp_id", emp_id).execute()
    # fcm_tok = tokens.data[0]["fcm_token"].strip()
    # print(fcm_tok)
    # send_notification(fcm_tok,"Rescheduled Shift Assigned", f"Shift Re-scheduled for data['client_id'] from {updated_shift.data['shift_start_time']} to {updated_shift.data['shift_end_time']}, time: {datetime.now()}. Do you accept or reject the offer.")

    return jsonify({
        "client": client.data,
        "updated_shift": updated_shift.data
    })

@app.route('/newShiftSchedule', methods=['GET'])
def newShiftSchedule():
    print("Hi")
    changes = detect_unassigned_shifts()

    # If changes found, trigger scheduling function
    if changes["new_clients"]:
        run_scheduling(changes)

    return jsonify(changes)


# ---- Function to check changes ----
def detect_unassigned_shifts():
    global last_known_clients, last_known_shifts

    changes = {"new_clients": [], "updated_shifts": []}

    # 1. Get all client IDs

    # Fetch shift details for new clients where shift_status is NULL
    shifts = supabase.table("shift") \
        .select("shift_id","client_id, shift_start_time, shift_end_time, date") \
        .is_("shift_status", None) \
        .execute()

    if shifts.data:
        changes["new_clients"].extend(shifts.data)

    # last_known_clients = current_clients
    return changes

@app.route('/newClientSchedule', methods=['GET'])
def newClientSchedule():
    print("Hi")
    changes = detect_changes()

    # If changes found, trigger scheduling function
    if changes["new_clients"]:
        run_scheduling(changes)

    return jsonify(changes)


last_known_clients = set()
last_known_shifts = {}


# ---- Function to check changes ----
def detect_changes():
    global last_known_clients, last_known_shifts

    changes = {"new_clients": [], "updated_shifts": []}

    # 1. Get all client IDs
    clients = supabase.table("client").select("client_id").execute()
    current_clients = {row["client_id"] for row in clients.data}

    # 2. Detect new clients
    new_clients = current_clients - last_known_clients
    if new_clients:
        # Fetch shift details for new clients where shift_status is NULL
        shifts = supabase.table("shift") \
            .select("shift_id","client_id, shift_start_time, shift_end_time, date") \
            .in_("client_id", list(new_clients)) \
            .is_("shift_status", None) \
            .execute()

        if shifts.data:
            changes["new_clients"].extend(shifts.data)

    last_known_clients = current_clients
    return changes

def parse_datetime(tstr: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S",  "%d-%m-%Y %H:%M%S"):
        try:
            return datetime.strptime(tstr, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unknown datetime format: {tstr}")

def overlaps(em,client_start_time, client_end_time, dsst, dset, ssst, sset):
    """Check if time overlaps."""
    print(em)
    if(dsst=="" or dset==""):
        return False
    elif(ssst=="" and sset==""):
        client_start_dt = parse_datetime(client_start_time)
        client_end_dt   = parse_datetime(client_end_time)
        dsst_dt         = parse_datetime(dsst)
        dset_dt         = parse_datetime(dset)
        return ((client_start_dt < client_end_dt
            and client_start_dt >= dsst_dt and client_start_dt <= dset_dt
            and client_end_dt >= dsst_dt and client_end_dt <= dset_dt))
    else:
        client_start_dt = parse_datetime(client_start_time)
        client_end_dt   = parse_datetime(client_end_time)
        dsst_dt         = parse_datetime(dsst)
        dset_dt         = parse_datetime(dset)
        ssst_dt         = parse_datetime(ssst)
        sset_dt         = parse_datetime(sset)
        print(client_start_dt,client_end_dt)
        return (
            (client_start_dt < client_end_dt
            and client_start_dt >= dsst_dt and client_start_dt <= dset_dt
            and client_end_dt >= dsst_dt and client_end_dt <= dset_dt)
            and not ((client_start_dt > ssst_dt and client_start_dt < sset_dt)
                    or (client_end_dt > ssst_dt and client_end_dt < sset_dt))
        )


def get_employees_for_shift(dateofshift):
    print("Hi3")
    today = dateofshift  # or use date.today()
    print("Today date is: ", today)

    # Join equivalent needs to be handled in Supabase: fetch and merge in Python
    employee = supabase.table("employee").select("emp_id,seniority, employee_type").order("seniority", desc=False).execute()
    daily_shifts = supabase.table("daily_shift").select("emp_id, shift_start_time, shift_end_time, shift_date").eq("shift_date", str(today)).execute()
    shifts = supabase.table("shift").select("emp_id, shift_start_time, shift_end_time, date").eq("date",str(today)).execute()
    leaves_raw = supabase.table("leaves").select("emp_id, leave_start_date, leave_start_time, leave_end_date, leave_end_time").execute().data
    leaves = []
    for lv in leaves_raw:
        start = lv["leave_start_date"]
        end   = lv["leave_end_date"]

        if start <= today <= end:
            leaves.append(lv)

    # Merge results into employee dicts
    merged = []
    for e in employee.data:
        emp_id = e["emp_id"]
        ds = next((ds for ds in daily_shifts.data if ds["emp_id"] == emp_id), None)
        s = next((s for s in shifts.data if s["emp_id"] == emp_id), None)
        emp_leaves = [
        {
            "start": f"{lv['leave_start_date']} {lv['leave_start_time']}",
            "end": f"{lv['leave_end_date']} {lv['leave_end_time']}"
        }
        for lv in leaves if lv["emp_id"] == emp_id
]
        if ds and s:
            merged.append({
                "emp_id": emp_id,
                "dsst": ds["shift_start_time"],
                "dset": ds["shift_end_time"],
                "ssst": s["shift_start_time"],
                "sset": s["shift_end_time"],
                "leaves": emp_leaves,
                "employee_type":e["employee_type"],
            })
        elif ds and not s:
            merged.append({
                "emp_id": emp_id,
                "dsst": ds["shift_start_time"],
                "dset": ds["shift_end_time"],
                "ssst": "",
                "sset": "",
                "leaves": emp_leaves,
                "employee_type":e["employee_type"],
            })
    print(merged)
    return merged

def overlaps_datetime(start1, end1, start2, end2):
    print(start1, end1, start2, end2)
    return start1 < end2 and end1 > start2

EMPLOYMENT_PRIORITY = {
    "Full Time": 1,
    "Part Time": 2,
    "Casual": 3
}

from datetime import datetime

def assign_tasks(changes):

    for ch in changes["new_clients"]:
        employeetab = get_employees_for_shift(ch['date'])

        eligible = [
            e for e in employeetab
            if (
                overlaps(
                    e,
                    ch['shift_start_time'], ch['shift_end_time'],
                    e['dsst'], e['dset'], e['ssst'], e['sset']
                )
                and (
                    e['leaves'] == []
                    or all(
                        not overlaps_datetime(
                            ch['shift_start_time'], ch['shift_end_time'],
                            lv['start'], lv['end']
                        )
                        for lv in e['leaves']
                    )
                )
            )
        ]

        if not eligible:
            print(f"No eligible employee for client {ch['client_id']}")
            continue

       
        eligible.sort(
            key=lambda e: (
                EMPLOYMENT_PRIORITY.get(e['employee_type'], 99)
            )
        )
        print("the eligible employees")
        print(eligible)
        shift_start = datetime.fromisoformat(ch['shift_start_time'])
        hours_to_shift = (shift_start - datetime.utcnow()).total_seconds() / 3600

        
        if hours_to_shift < 24:
            best_employee = eligible[0]

            supabase.table("shift").update({
                "emp_id": best_employee['emp_id'],
                "shift_status": "Scheduled"
            }).eq("shift_id", ch['shift_id']).execute()

            notify_employee(
                best_employee["emp_id"],
                {
                    "type": "shift_offer",
                    "shift_id": ch["shift_id"],
                    "message": "A shift is available. Accept or Reject."
                }
            )

            print(f"[AUTO] Assigned shift {ch['shift_id']} to {best_employee['emp_id']}")

        # ============================================================
        # CASE B: ≥ 24 HOURS → OFFER-BASED FLOW
        # ============================================================
        else:
            offers = []

            for idx, e in enumerate(eligible, start=1):
                offers.append({
                    "shift_id": ch["shift_id"],
                    "emp_id": e["emp_id"],
                    "status": "sent" if idx == 1 else "pending",
                    "offer_order": idx,
                    "sent_at": datetime.utcnow().isoformat() if idx == 1 else None
                })

            # Insert all offers together
            supabase.table("shift_offers").insert(offers).execute()

            first_emp = eligible[0]

            notify_employee(
                first_emp["emp_id"],
                {
                    "type": "shift_offer",
                    "shift_id": ch["shift_id"],
                    "message": "A shift is available. Accept or Reject."
                }
            )

            # send_notification(**notification)
            #print(notification)

            # Update shift status
            supabase.table("shift").update({
                "shift_status": "Offer Sent"
            }).eq("shift_id", ch["shift_id"]).execute()

            print(f"[OFFER] Shift {ch['shift_id']} sent to {first_emp['emp_id']}")

        #tokens = supabase.table("employee_tokens").select("fcm_token").eq("emp_id", best_employee['emp_id']).execute()
        # fcm_tok = tokens.data[0]["fcm_token"].strip()
        # print(fcm_tok)
        # send_notification(fcm_tok,"New Shift Assigned", f"Shift scheduled from {ch['shift_start_time']} to {ch['shift_end_time']}, time: {datetime.now()}")
        schedule()

def accept_shift_offer(shift_id, emp_id):

    assigned = (
        supabase.table("shift")
        .select("emp_id")
        .eq("shift_id", shift_id)
        .execute()
    )

    if assigned.data and assigned.data[0]["emp_id"]:
        return {"error": "Shift already assigned"}

    supabase.table("shift").update({
        "emp_id": emp_id,
        "shift_status": "Scheduled"
    }).eq("shift_id", shift_id).execute()

    supabase.table("shift_offers").update({
        "status": "accepted",
        "responded_at": datetime.utcnow().isoformat()
    }).eq("shift_id", shift_id).eq("emp_id", emp_id).execute()

    supabase.table("shift_offers").update({
        "status": "expired"
    }).eq("shift_id", shift_id).neq("emp_id", emp_id).execute()

    return {"success": True}

def activate_next_offer(shift_id):
    # Get current offers ordered by priority
    offers = supabase.table("shift_offers") \
        .select("*") \
        .eq("shift_id", shift_id) \
        .order("offer_order") \
        .execute().data

    # Find next pending employee
    next_offer = next((o for o in offers if o["status"] == "pending"), None)

    if not next_offer:
        # No one left
        supabase.table("shift").update({
            "shift_status": "Unassigned"
        }).eq("shift_id", shift_id).execute()

        print(f"[FAILED] No employee accepted shift {shift_id}")
        return

    # Activate next offer
    supabase.table("shift_offers").update({
        "status": "sent",
        "sent_at": datetime.utcnow().isoformat()
    }).eq("id", next_offer["id"]).execute()

    '''send_notification(
        next_offer["emp_id"],
        "Shift Available",
        "A shift is available. Accept to be assigned.",
        "shift_offer",
        {"shift_id": shift_id}
    )'''

    print(f"[NEXT OFFER] Sent to {next_offer['emp_id']}")


# ---- Your Scheduling Logic ----
def run_scheduling(changes):
    print("Scheduling triggered due to changes:", changes)
    assign_tasks(changes)

@app_notif.websocket("/ws/{emp_id}")
async def websocket_endpoint(websocket: WebSocket, emp_id: int):
    await websocket.accept()
    active_connections[int(emp_id)] = websocket
    print(f"[WS CONNECTED] emp_id={emp_id}")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.pop(int(emp_id), None)
        print(f"[WS DISCONNECTED] emp_id={emp_id}")

async def send_offer_notification(emp_id, shift_id):
    ws = active_connections.get(emp_id)
    if ws:
        await ws.send_text(json.dumps({
            "type": "shift_offer",
            "shift_id": shift_id,
            "message": "A shift is available. Accept or Reject."
        }))

def notify_employee(emp_id: int, payload: dict):
    ws = active_connections.get(emp_id)
    if not ws:
        print(f"[WS OFFLINE] emp_id={emp_id}")
        return

    async def _send():
        await ws.send_text(json.dumps(payload))

    asyncio.create_task(_send())

@app.route("/shift_offer/respond", methods=["POST"])
def respond_to_offer():
    data = request.json
    shift_id = data["shift_id"]
    emp_id = data["emp_id"]
    response = data["response"]  # accepted / rejected

    if response == "accepted":
        accept_shift_offer(shift_id, emp_id)

        notify_employee(
            emp_id,
            {
                "type": "offer_result",
                "status": "accepted",
                "shift_id": shift_id
            }
        )
        return jsonify({"status": "assigned"}), 200

    else:
        supabase.table("shift_offers").update({
            "status": "rejected",
            "responded_at": datetime.utcnow().isoformat()
        }).eq("shift_id", shift_id).eq("emp_id", emp_id).execute()

        activate_next_offer(shift_id)
        return jsonify({"status": "rejected"}), 200



@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    required = ["password", "first_name", "last_name"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # Hash password
    hashed_pw = generate_password_hash(data["password"])
    newemp_id = supabase.table("employee").select("emp_id").order("emp_id", desc=True).limit(1).execute().data[0]["emp_id"] + 1
    response = supabase.table("employee").insert({
        "emp_id": newemp_id,
        "first_name": data["first_name"],
        "last_name": data["last_name"],
        "date_of_birth": data.get("date_of_birth"),
        "gender": data.get("gender"),
        "password": hashed_pw
    }).execute()

    # Map weekday names to numbers
    days_map = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6
    }

    week_daily_timeline = data.get("weekshift")
    newshift_id = 1

    # Fetch the latest emp_daily_id (if any)
    response = supabase.table("employee_daily_timeline") \
        .select("emp_daily_id") \
        .order("emp_daily_id", desc=True) \
        .limit(1) \
        .execute()

    # Check if any data is returned
    if response.data and len(response.data) > 0:
        newshift_id = response.data[0]["emp_daily_id"] + 1
    today = datetime.now().date()
    for item in week_daily_timeline:
        day_item = item.get("day")
        day_num = days_map.get(day_item)
        day_diff = (day_num - today.weekday() + 7) % 7
        shift_date = today + timedelta(days=day_diff)
        yr, mm, dd = str(shift_date).split("-")
        final_date = dd+"-"+mm+"-"+yr
        for ind,sh in enumerate(item.get("shifts")):
            resp = supabase.table("employee_daily_timeline").insert({
                "emp_daily_id": newshift_id,
                "emp_id": newemp_id,
                "shift_start_time":str(sh["start"]),
                "shift_end_time":str(sh["end"]),
                "week_day": day_item
            }).execute()
            
            ds = supabase.table("daily_shift").insert({
                "shift_date":str(final_date),
                "emp_id": newemp_id,
                "shift_type": "flw-rtw",
                "shift_start_time":f"{shift_date} {sh["start"]}:00",
                "shift_end_time":f"{shift_date} {sh["end"]}:00"
            }).execute()


    return jsonify({"message": "Registered successfully", "data": response.data}), 201

@app.route('/register/client', methods=['POST'])
def register_client():
    data = request.get_json(silent=True) or {}
    response = supabase.table("client").select("client_id").eq("email",data.get('email')).execute()
    if(response.data):
        return jsonify({"message": f"Client ID already exists {response.data}"}), 409
    else:
        fmt = "%Y-%m-%d"
        dob = data['date_of_birth']
        result = supabase.table("client").select("*", count="exact").execute()
        lastcid = result.count +1
        dateofbirth=dob
        # print(firstname,lastname,gender,dateofbirth)
        response = supabase.table("client").insert({
            "client_id": lastcid,
            "first_name": data['first_name'],
            "last_name": data['last_name'],
            "date_of_birth": dateofbirth,
            "phone": data['phone_number'],
            "gender": data['gender'],
            "name": data['first_name'],
            "address_line1":data['address'],
            "image_url": data['image'],
            "password":data['password'],
            "preferred_language":data['preferred_language']
            }).execute()
        week_app_idx = supabase.table("client_weekly_schedule").select("*", count="exact").execute()
        if(response):
            print(data['weekshift'])
            weekdetail = data['weekshift']
            weekidx = week_app_idx.count + 1
            for ind,item in enumerate(weekdetail):
                if item["shifts"] != []:
                    for i, timeshift in enumerate(item["shifts"]):
                        weekres = (
                            supabase.table("client_weekly_schedule")
                            .insert({
                                "week_schedule_id":weekidx,
                                "client_id":lastcid,
                                "week_day":item["day"],
                                "end_time":timeshift["end"],
                                "start_time":timeshift["start"]})
                            .execute()
                        )
                        weekidx = weekidx + 1
                        print(weekres.data)
            client_id = response.data[0]["client_id"]
            return jsonify({
                "message": "Client registered successfully",
                "client_id": client_id
            }), 200
        return jsonify({"message": "Registered successfully"}), 201
def convtime(tinp):
    #day, month, rest = tinp.split("-")
    dat, time = tinp.split("T")
    conv_time= dat+" "+time
    return conv_time
def convDate(dt):
    year, month, day = dt.split("-")
    conv_dt = day+"-"+month+"-"+year
    return conv_dt

@app.route('/prepareSchedule', methods=['POST'])
def prepare_schedule():
    data = request.get_json()
    client_id = data.get("client_id")
    weekshift = data.get("weekshift", [])

    today = datetime.now().date()
    total_weeks = 1  # You can make this dynamic
    inserted_shifts = []

    # Map weekday names to numbers
    days_map = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6
    }
    newshift_id = supabase.table("shift").select("shift_id").order("shift_id", desc=True).limit(1).execute().data[0]["shift_id"] + 1
    for ws in weekshift:
        day_name = ws.get("day")
        day_num = days_map.get(day_name)
        if day_num is None:
            break
        if len(ws.get("shifts")) > 0:
            for sh in ws.get("shifts"):
                start_time = sh.get("start")
                end_time = sh.get("end")
                # Generate next 4 occurrences of this day
                for week in range(total_weeks):
                    day_diff = (day_num - today.weekday() + 7) % 7 + (week * 7)
                    shift_date = today + timedelta(days=day_diff)

                    shift_start = f"{shift_date} {start_time}:00"
                    shift_end = f"{shift_date} {end_time}:00"
                    yr, mm, dd = str(shift_date).split("-")
                    final_date = dd+"-"+mm+"-"+yr
                    response = supabase.table("shift").insert({
                        "shift_id": newshift_id,
                        "client_id": client_id,
                        "shift_start_time": shift_start,
                        "shift_end_time": shift_end,
                        "shift_status": "Unassigned",
                        "emp_id": None,
                        "date": str(final_date)
                    }).execute()
                    newshift_id = newshift_id + 1
                    inserted_shifts.append({
                        "date": str(shift_date),
                        "start": start_time,
                        "end": end_time
                    })
                    # print(get_employees().get_data(as_text=True))
                    changes = {"new_clients": [], "updated_shifts": []}
                    shifts = supabase.table("shift") \
                            .select("shift_id","client_id, shift_start_time, shift_end_time, date") \
                            .eq("client_id", client_id) \
                            .eq("shift_status", "Unassigned") \
                            .execute()

                    if shifts.data:
                        changes["new_clients"].extend(shifts.data)
                    print("Shift changes",changes)
                    run_scheduling(changes)
            
        if not day_name:
            continue
    return jsonify({
        "message": f"Prepared {len(inserted_shifts)} shifts for Client {client_id}.",
        "details": inserted_shifts
    })



@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400
            
        emp_id_str = data.get("employeeId")
        password = data.get("password")
        
        # Convert to int safely
        try:
            emp_id = int(emp_id_str)
        except:
            return jsonify({"error": "Employee ID must be a number"}), 400
            
        if not emp_id or not password:
            return jsonify({"error": "Employee ID and password required"}), 400

        # Fetch employee
        response = supabase.table("employee").select("*").eq("emp_id", emp_id).execute()
        
        if not response.data:
            return jsonify({"error": "Employee not found"}), 400
            
        employee = response.data[0]
        
        # PLAIN TEXT PASSWORD (matches your DB)
        if employee["password"] != password:
            return jsonify({"error": "Wrong password"}), 400

        # Simple token (no JWT complexity)
        token = f"token_{employee['emp_id']}_{employee.get('emp_role', 'WORKER')}"
        
        return jsonify({
            "success": True,
            "message": "Login OK",
            "token": token,
            "user": {
                "emp_id": employee["emp_id"],
                "emp_role": employee.get("emp_role", "WORKER"),
                "first_name": employee["first_name"],
                "email": employee.get("email", "")
            }
        }), 200
        
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({"error": str(e)}), 500




@app.route('/protected')
def protected():
    if 'emp_id' in session:
        return jsonify({'message': f'Welcome, user {session['emp_id']}!'})
    else:
        return jsonify({'message': 'Unauthorized'}), 401


@app.route('/logout')
def logout():
    session.pop('emp_id', None)
    return jsonify({'message': 'Logged out successfully'})

@app.route('/clients', methods=['GET'])
def get_clients():
    try:
        # Fetch all rows from client table
        response = supabase.table("client").select("*").execute()

        if response:
            return jsonify({"client": response.data})
        return jsonify({"error": str(response.error)}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
STATUS_CONFIG = {
    "TRAINING": {"label": "TRN", "color": "green"},
    "FLW-RTW": {"label": "FLW", "color": "green"},

    "LEAVE": {"label": "LV", "color": "red"},

    "CLOCKED_IN": {"label": "IN", "color": "orange"},
    "CLOCKED_OUT": {"label": "OUT", "color": "aqua"},

    "OFFER_SENT": {"label": "OFR", "color": "purple"},

    "WAITING": {"label": "WT", "color": "gray"}
}

@app.route('/employees', methods=['GET'])
def get_employees():
    try:
        # Fetch all employees
        response = get_employees_with_status()
        


        if response:
            return response
        return jsonify({"error": str(response)}), 400
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def resolve_employee_status(emp_id, shifts, leaves):

    # 1️⃣ Training / FLW / RTW
    for s in shifts:
        if s["emp_id"] == emp_id and s["shift_type"] in ["training", "flw-rtw"]:
            return STATUS_CONFIG["TRAINING"]

    # 2️⃣ Leave
    for l in leaves:
        if l["emp_id"] == emp_id:
            return STATUS_CONFIG["LEAVE"]

    # 3️⃣ Clocked In
    '''for a in attendance:
        if a["emp_id"] == emp_id and a.get("clock_in") and not a.get("clock_out"):
            return STATUS_CONFIG["CLOCKED_IN"]

    # 4️⃣ Clocked Out
    for a in attendance:
        if a["emp_id"] == emp_id and a.get("clock_out"):
            return STATUS_CONFIG["CLOCKED_OUT"]

    # 5️⃣ Offer Sent
    for o in offers:
        if o["emp_id"] == emp_id:
            return STATUS_CONFIG["OFFER_SENT"]'''

    # 6️⃣ Waiting
    return STATUS_CONFIG["WAITING"]
def get_employees_with_status():

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    employees = supabase.table("employee").select("*").execute().data
    shifts = supabase.table("daily_shift") \
        .select("*") \
        .lte("shift_start_time", now_str) \
        .gte("shift_end_time", now_str) \
        .execute().data

    leaves = supabase.table("leaves") \
        .select("*") \
        .lte("leave_start_date", today_str) \
        .gte("leave_end_date", today_str) \
        .execute().data
    #attendance = supabase.table("attendance").select("*").execute().data
    #offers = supabase.table("offers").eq("status", "sent").execute().data

    result = []

    for emp in employees:
        status = resolve_employee_status(
            emp["emp_id"],
            shifts,
            leaves,
            
        )

        result.append({
            "emp_id": emp["emp_id"],
            "first_name": emp["first_name"],
            "last_name": emp.get("last_name", ""),
            "service_type": emp.get("service_type"),
            "status": status
        })

    return result
        
@app.route("/injury_reports", methods=["GET"])
def get_injury_reports():
    response = supabase.table("injury_reports").select("*").execute()
    return jsonify(response.data)


SUPERVISOR_EMAIL = "hemangee4700@gmail.com"

@app.route("/send_injury_report", methods=["POST"])
def send_injury_report():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    try:
        subject = f"🚨 New Injury Report — {data['injured_person']}"
        body = f"""
        <h3>🚨 New Injury Report</h3>
        <p>This is an automated notification from the Gerri Assist.</p>

        <ul>
            <li><b>Date of Incident:</b> {data['date_of_incident']}</li>
            <li><b>Injured Person:</b> {data['injured_person']}</li>
            <li><b>Reported By:</b> {data['reported_by']}</li>
            <li><b>Location:</b> {data['location']}</li>
        </ul>

        <h4>🩹 Injury Details:</h4>
        <p>{data['injury_details']}</p>

        <h4>⚕️ Action Taken:</h4>
        <p>{data['action_taken']}</p>
        """
        date_of_incident = data.get("date_of_incident")
        injured_person = data.get("injured_person")
        reported_by = data.get("reported_by")
        location = data.get("location")
        injury_details = data.get("injury_details")
        action_taken = data.get("action_taken")
        severity = data.get("severity")

        msg = MIMEMultipart()
        msg["From"] = "hemangee4700@gmail.com"
        msg["To"] = SUPERVISOR_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        # SMTP Setup (for example Gmail)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login("hemangee4700@gmail.com", "hvvm jfdz rkjs ynly")
            smtp.send_message(msg)
        insert_data = {
            "date": date_of_incident,
            "injured_person": injured_person,
            "reporting_employee": reported_by,
            "location": location,
            "description": injury_details,
            "status": action_taken,
            "severity": severity
        }

        supabase.table("injury_reports").insert(insert_data).execute()
        print("✅ Record inserted into Supabase")
        return jsonify({"message": "Email sent successfully"}), 200

    except Exception as e:
        print("Error sending email:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/add_client_shift", methods=["POST"])
def add_client_shift():
    data = request.get_json()
    try:
        supabase.table("shift").insert({
            "client_id": data["client_id"],
            "emp_id":data["emp_id"],
            "shift_start_time": data["shift_start_time"],
            "shift_end_time": data["shift_end_time"],
            "date":data["shift_date"],
            "shift_status": data['shift_status'],
        }).execute()

        return jsonify({"message": "Client shift added"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/add_employee_shift", methods=["POST"])
def add_employee_shift():
    data = request.get_json()
    try:
        supabase.table("daily_shift").insert({
            "emp_id": data["emp_id"],
            "shift_date": data["shift_date"],
            "shift_start_time": data["shift_start_time"],
            "shift_end_time": data["shift_end_time"],
            "shift_type": data["shift_type"]
        }).execute()

        return jsonify({"message": "Employee daily shift added"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generate_next_month_shifts", methods=["POST"])
def generate_next_month_shifts():
    try:
        data = request.get_json()
        emp_id = data.get("emp_id")

        if not emp_id:
            return jsonify({"error": "emp_id is required"}), 400

        # 1️⃣ Fetch weekly shift template
        timeline_res = (
            supabase.table("employee_daily_timeline")
            .select("week_day, shift_start_time, shift_end_time")
            .eq("emp_id", emp_id)
            .execute()
        )

        if not timeline_res.data:
            return jsonify({"error": "No weekly timeline found"}), 404

        timeline_map = {
            row["week_day"].capitalize(): {
                "start": row["shift_start_time"],
                "end": row["shift_end_time"]
            }
            for row in timeline_res.data
        }

        # 2️⃣ Find last scheduled shift date
        last_shift_res = (
            supabase.table("daily_shift")
            .select("shift_date")
            .eq("emp_id", emp_id)
            .order("shift_date", desc=True)
            .limit(1)
            .execute()
        )

        if last_shift_res.data:
            start_date = datetime.strptime(
                last_shift_res.data[0]["shift_date"], "%Y-%m-%d"
            ) + timedelta(days=1)
        else:
            start_date = datetime.today()

        # 3️⃣ End date = 6 weeks (42 days)
        end_date = start_date + timedelta(days=41)

        # 4️⃣ Generate shifts
        new_entries = []
        current_date = start_date

        while current_date <= end_date:
            weekday = current_date.strftime("%A")

            if weekday in timeline_map:
                date_str = current_date.strftime("%Y-%m-%d")
                start_time = timeline_map[weekday]["start"]
                end_time = timeline_map[weekday]["end"]

                new_entries.append({
                    "emp_id": emp_id,
                    "shift_date": date_str,
                    "shift_start_time": f"{date_str} {start_time}",
                    "shift_end_time": f"{date_str} {end_time}",
                    "shift_type": "flw-rtw"
                })

            current_date += timedelta(days=1)

        # 5️⃣ Insert into Supabase
        if new_entries:
            supabase.table("daily_shift").insert(new_entries).execute()

        return jsonify({
            "message": "Next 6 weeks schedule generated",
            "count": len(new_entries),
            "from": start_date.strftime("%Y-%m-%d"),
            "to": end_date.strftime("%Y-%m-%d")
        }), 200

    except Exception as e:
        print("Error generating shifts:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/client_generate_next_month_shifts", methods=["POST"])
def client_generate_next_month_shifts():
    try:
        data = request.get_json()
        client_id = data.get("client_id")

        if not client_id:
            return jsonify({"error": "client_id is required"}), 400

        # 1️⃣ Fetch weekly schedule template
        weekly_timeline = (
            supabase.table("client_weekly_schedule")
            .select("week_day, start_time, end_time")
            .eq("client_id", client_id)
            .execute()
        )

        if not weekly_timeline.data:
            return jsonify({"error": "No weekly schedule found for client"}), 404

        timeline_map = {
            row["week_day"].capitalize(): {
                "start": row["start_time"],
                "end": row["end_time"]
            }
            for row in weekly_timeline.data
        }

        # 2️⃣ Find last scheduled date
        last_shift_res = (
            supabase.table("shift")
            .select("date")
            .eq("client_id", client_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )

        if last_shift_res.data:
            start_date = datetime.strptime(
                last_shift_res.data[0]["date"], "%Y-%m-%d"
            ) + timedelta(days=1)
        else:
            start_date = datetime.today()

        # 3️⃣ 6-week window
        end_date = start_date + timedelta(days=41)

        # 4️⃣ Generate shifts
        new_entries = []
        current_date = start_date

        while current_date <= end_date:
            weekday = current_date.strftime("%A")

            if weekday in timeline_map:
                date_str = current_date.strftime("%Y-%m-%d")
                start_time = timeline_map[weekday]["start"]
                end_time = timeline_map[weekday]["end"]

                new_entries.append({
                    "client_id": client_id,
                    "date": date_str,
                    "shift_start_time": f"{date_str} {start_time}",
                    "shift_end_time": f"{date_str} {end_time}",
                })

            current_date += timedelta(days=1)

        # 5️⃣ Insert into Supabase
        if new_entries:
            supabase.table("shift").insert(new_entries).execute()

        return jsonify({
            "message": "Next 6 weeks shifts generated",
            "count": len(new_entries),
            "from": start_date.strftime("%Y-%m-%d"),
            "to": end_date.strftime("%Y-%m-%d")
        }), 200

    except Exception as e:
        print("Error generating shifts:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/employees/<int:emp_id>")
def get_employee_with_id(emp_id):
    emp = supabase.table("employee").select("*").eq("emp_id", emp_id).execute()
    shift = supabase.table("shift").select("*").eq("emp_id", emp_id).execute()
    dailyshift = supabase.table("daily_shift").select("*").eq("emp_id", emp_id).execute()
    data = {
        "employee": emp.data,
        "shift": shift.data,
        "dailyshift": dailyshift.data,
    }
    return jsonify(data)

@app.route("/unavailability/<emp_id>", methods=["GET"])
def get_unavailability(emp_id):
    data = supabase.table("leaves").select("*").eq("emp_id", emp_id).execute()
    return jsonify({ "unavailability": data.data })

@app.route("/add_unavailability", methods=["POST"])
def add_unavailability():
    req = request.get_json()

    supabase.table("leaves").insert({
        "emp_id": req["emp_id"],
        "leave_type": req["type"],
        "leave_start_date": req["start_date"],
        "leave_end_date": req["end_date"],
        "leave_reason": req["description"],
        "leave_start_time": req["start_time"],
        "leave_end_time": req["end_time"],
    }).execute()
    leave_processing(req["emp_id"],req["start_date"],req["end_date"],req["start_time"],req["end_time"]);

    return jsonify({"message": "Unavailability added successfully"})
def leave_processing(emp_id,leave_start_date,leave_end_date,leave_start_time,leave_end_time):
    # Convert full timestamps
    leave_start = f"{leave_start_date} {leave_start_time}"
    leave_end = f"{leave_end_date} {leave_end_time}"

    # 2️⃣ Fetch existing assigned shifts
    assigned_shifts = supabase.table("shift") \
        .select("*") \
        .eq("emp_id", emp_id) \
        .eq("shift_status", "Scheduled") \
        .execute().data

    def overlaps(s, e, ls, le):
        return not (e <= ls or s >= le)

    # 3️⃣ Find affected shifts → mark them unassigned
    unassigned = []
    for s in assigned_shifts:
        if overlaps(s["shift_start_time"], s["shift_end_time"], leave_start, leave_end):
            supabase.table("shift").update({
                "emp_id": None,
                "shift_status": "Unassigned"
            }).eq("shift_id", s["shift_id"]).execute()
            unassigned.append(s)

    # 4️⃣ Auto-reschedule the unassigned items
    if unassigned:
        changes = {"new_clients": unassigned}
        print("Unassigned", changes)
        assign_tasks(changes)

    return jsonify({
        "message": "Leave applied & affected shifts rescheduled",
        "unassigned_count": len(unassigned)
    }), 200

@app.route("/update_unavailability/<int:leave_id>", methods=["PUT"])
def update_unavailability(leave_id):
    data = request.json
    supabase.table("leaves").update(data).eq("leave_id", leave_id).execute()
    return jsonify({"message": "updated"}), 200

@app.route("/delete_unavailability/<int:leave_id>", methods=["DELETE"])
def delete_unavailability(leave_id):
    supabase.table("leaves").delete().eq("leave_id", leave_id).execute()
    return jsonify({"message": "deleted"}), 200

@app.route("/update_employee_settings/<emp_id>", methods=["POST"])
def update_employee_settings(emp_id):
    data = request.json
    print(data.keys(), data.values())
    clean_data = {}

    for key, value in data.items():

        # Remove invalid values
        if value in [None, "", "undefined", "null", "NaN"]:
            continue

        # TRY to convert number strings safely
        try:
            if isinstance(value, str) and value.isdigit():
                clean_data[key] = int(value)
            else:
                clean_data[key] = value
        except:
            # If conversion fails, skip this field
            continue

    if not clean_data:
        return jsonify({"status": "error", "message": "No valid fields to update"}), 400
    print(data)
    try:
        update_result = supabase.table("employee").update(data).eq("emp_id", emp_id).execute()

        return jsonify({"status": "success", "updated": update_result.data}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/masterSchedule/<service>", methods=["GET"])
def masterSchedule(service: str):
    print(service)
    emp_res = supabase.table("employee") \
        .select("emp_id, first_name, address") \
        .eq("service_type", service) \
        .execute()
    employees = emp_res.data

    start_date = date.today()
    dates = get_6_week_dates(start_date)

    output_employees = []

    for emp in employees:
        print(emp["first_name"])
        shifts = []
        #print(dates[-1])
        # 3️⃣ Get all shifts for this employee in date range
        shift_res = supabase.table("daily_shift") \
            .select("*") \
            .eq("emp_id", emp["emp_id"]) \
            .gte("shift_date", dates[0]) \
            .lte("shift_date", dates[-1]) \
            .execute()
        #print(shift_res)
        shift_map = {
            s["shift_date"]: s for s in shift_res.data
        }
        
        for d in dates:
            #print(shift_map[str(d)])
            shift = shift_map.get(d.isoformat())
            print(shift)
            if not shift:
                # open shift / empty
                shifts.append({
                    "time": "",
                    "type": "open",
                    "training": False
                })
                continue
            
            # 4️⃣ Apply shift notation
            shift_date = datetime.fromisoformat(shift["shift_date"])
            start_time = datetime.fromisoformat(shift["shift_start_time"])
            end_time = datetime.fromisoformat(shift["shift_end_time"])

            if service == "Outreach":
                time_code = f"{start_time.strftime('%H:%M:%S')}-{end_time.strftime('%H:%M:%S')}"

            else:
                noon_cutoff = shift_date.replace(hour=12, minute=0, second=0)
                evening_cutoff = shift_date.replace(hour=18, minute=0, second=0)

                if end_time <= noon_cutoff:
                    shift["shift_code"] = "day"        # d
                elif start_time > noon_cutoff and end_time <= evening_cutoff:
                    shift["shift_code"] = "noon"       # n
                else:
                    shift["shift_code"] = "evening"    # e

                time_code = SHIFT_CONVENTIONS[service][shift["shift_code"]]

            shifts.append({
                "time": time_code,
                "type": SHIFT_TYPE_MAP.get(shift["shift_type"], ""),
                "training": shift.get("training", False)
            })
        
        leave_res = supabase.table("leaves") \
            .select("*") \
            .eq("emp_id", emp["emp_id"]) \
            .gte("leave_start_date", dates[0]) \
            .lte("leave_end_date", dates[-1]) \
            .execute()
        leaves = leave_res.data or []
        print(leaves)
        leave_map = {}

        for leave in leaves:
            start = datetime.fromisoformat(leave["leave_start_date"]).date()
            end = datetime.fromisoformat(leave["leave_end_date"]).date()

            d = start
            while d <= end:
                leave_map[d] = leave
                d += timedelta(days=1)

        for idx,d in enumerate(dates):
            if d in leave_map:
                leave = leave_map[d]

                leave_type = leave.get("leave_type", "").lower()
                
                # Determine shift type (color)
                if leave_type == "sick paid" or leave_type == "sick unpaid":
                    shift_type = SHIFT_TYPE_MAP["sick"]
                elif leave_type == "maternity/paternity leave" or leave_type == "wsib leave (with seniority)" or leave_type == "esa leave + seniority" or leave_type == "unpaid leave + no seniority":
                    shift_type = SHIFT_TYPE_MAP["leave"]
                elif leave_type == "bereavement paid" or leave_type == "bereavement unpaid":
                    shift_type = SHIFT_TYPE_MAP["bereavement"]
                elif leave_type == "vacation ft hourly - pay only" or leave_type == "vacation pt and casual - seniority only":  # keeping your DB spelling
                    shift_type = SHIFT_TYPE_MAP["vacation"]
                elif leave_type == "float day":
                    shift_type = SHIFT_TYPE_MAP["float"]
                else:
                    shift_type = SHIFT_TYPE_MAP["unavailability"]

                # Override shift
                shifts[idx]={
                    "time": "",              # no d/n/e for leave
                    "type": shift_type,
                    "training": False
                }
                continue

        
        output_employees.append({
        "id": emp["emp_id"],
        "name": emp["first_name"],
        "address": emp["address"],
        "shifts": shifts
        })

    data= jsonify({
        "weeks": [d.strftime("%d-%b") for d in dates],
        "employees": output_employees
    })
    print(data)
    return data

SHIFT_CONVENTIONS = {
    "85 Neeve": {"day": "d", "noon": "n", "evening": "e"},
    "87 Neeve": {"day": "d",  "noon": "n",  "evening": "e"},
    "Willow Place": {"day": "D", "noon": "N", "evening": "E"},
    "Outreach": None  # handled separately
}
SHIFT_TYPE_MAP = {
    "vacation": "vacation",
    "float": "float",
    "unavailability": "unavailable",
    "flw-training": "flw-training",
    "gil-training": "gil",
    "flw-rtw": "flw-rtw",
    "open": "open",
    "leave": "leave",
    "sick": "sick",
    "bereavement": "bereavement",
}
def get_6_week_dates(start_date: date):
    return [start_date + timedelta(days=i) for i in range(42)]


# --- Run ---
if __name__ == '__main__':
    app.run(debug=True)

