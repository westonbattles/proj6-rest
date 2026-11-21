import os
import math
from flask import Flask, redirect, url_for, request, render_template, jsonify
from flask_restful import Resource, Api
from pymongo import MongoClient
import arrow
import acp_times # brevet calculation py file

app = Flask(__name__)
api = Api(app)

client = MongoClient(os.environ['DB_PORT_27017_TCP_ADDR'], 27017)
db = client.tododb

# BREVETS API
class Brevets(Resource):
    def get(self):

        brevets_dict = {
            "brevets": []
        }

        for brevet in db.tododb.find():
            start = arrow.get(
                f"{brevet['begin_date']} {brevet['begin_time']}", "YYYY-MM-DD HH:mm"
            )
            entry = {
                "distance": brevet["brevet_distance_km"],
                "begin_date": start.format("MM/DD/YYYY"),
                "begin_time": start.format("HH:mm"),
                "controls": [],
            }

            for control in brevet["controls"]:

                try: miles = float(control.get("miles"))
                except (TypeError, ValueError): miles = None

                # add our formated brevet controls to our brevet json entry
                entry["controls"].append({
                    "km": control["km"],
                    "mi": miles if miles is not None and math.isfinite(miles) else None,
                    "location": control.get("location") or None,
                    "open": arrow.get(control["open"]).format("MM/DD/YYYY HH:mm"),
                    "close": arrow.get(control["close"]).format("MM/DD/YYYY HH:mm"),
                })

            brevets_dict["brevets"].append(entry)

        return brevets_dict
        # return {
        #     "Fortnite": "Battle Pass"
        # }

class OpenTimes(Resource):
    def get(self):

        top = request.args.get('top', type=int)

        sorted_times = [
            control["open"]
            for brevet in db.tododb.find()
            for control in brevet["controls"]
        ]

        sorted_times = sorted(arrow.get(time) for time in sorted_times)
        open_times = [time.format("MM/DD/YYYY HH:mm") for time in sorted_times]

        if top is not None: open_times = open_times[:top]

        return open_times

api.add_resource(Brevets, '/listAll', '/listAll/json')
api.add_resource(OpenTimes, '/listOpenOnly', '/listOpenOnly/json')


@app.template_filter('control_time')
def format_control_time(value):
    return arrow.get(value).to('utc').format('ddd M/D H:mm')

@app.route("/")
@app.route("/index")
def index():
    app.logger.debug("Main page entry")
    return render_template('calc.html')


@app.route('/display')
def display():
    brevets = list(db.tododb.find())
    return render_template('display.html', brevets=brevets)

@app.route('/new', methods=['POST'])
def new():

    """request.form:

    distance:
    begin_date: (XXXX-XX-XX)
    begin_time: (XX:XX) (24h)
    miles: 
    km:
    location (optional)
    open:
    close:
    """

    print(request.form)
    #print("\n".join(f"{k}: {v}" for k, v in request.form.to_dict(flat=False).items()))

    distance = request.form.get('distance')
    begin_date = request.form.get('begin_date')
    begin_time = request.form.get('begin_time')

    # lists
    miles = request.form.getlist('miles')
    km = request.form.getlist('km')
    locations = request.form.getlist('location')

    #error handling
    if (distance == None or begin_date == None or begin_time == None):
        return render_template(
            "calc.html",
            error="Could not parse, please try again."
        ), 400

    controls = []

    for i, km_value in enumerate(km):
        if km_value.strip() == "": # string was empty
            continue

        controls.append(
            {
                'miles': miles[i].strip(),
                'km': km_value.strip(),
                'location': locations[i].strip(),
            }
        )

    # if controls are empty, error
    if not controls:
        return render_template(
            "calc.html",
            error="Enter at least one control before submitting."
        ), 400

    # use the start time and calculation functions
    try:
        distance = int(distance)
        start_time = arrow.get(
            f"{begin_date} {begin_time}", 'YYYY-MM-DD HH:mm'
        ).isoformat()
    except (TypeError, ValueError):
        return render_template(
            "calc.html",
            error="Enter a valid brevet distance, start date, and start time."
        ), 400

    if distance not in {200, 300, 400, 600, 1000}:
        return render_template(
            "calc.html",
            error="Choose a supported brevet distance."
        ), 400

    for control in controls:
        try:
            control_km = float(control['km'])
        except ValueError:
            return render_template(
                "calc.html", error="Control distances must be numbers."
            ), 400

        if not math.isfinite(control_km) or control_km < 0:
            return render_template(
                "calc.html",
                error="Control distances must be finite, nonnegative numbers."
            ), 400

        control['km'] = control_km
        control['open'] = acp_times.open_time(control_km, distance, start_time)
        control['close'] = acp_times.close_time(control_km, distance, start_time)
    
    item_doc = {
        'brevet_distance_km': distance,
        'begin_date': begin_date,
        'begin_time': begin_time,
        'controls': controls,
    }

    db.tododb.insert_one(item_doc)

    return redirect('/')




###############
#
# AJAX request handlers
#   These return JSON, rather than rendering pages.
#
###############
@app.route("/_calc_times")
def _calc_times():
    """
    Calculates open/close times from miles, using rules
    described at https://rusa.org/octime_alg.html.
    Expects one URL-encoded argument, the number of miles.
    """
    app.logger.debug("Got a JSON request")
    km = request.args.get('km', 999, type=float)
    brevet_dist_km = request.args.get('brevet_dist_km', 999, type=float)
    begin_date = request.args.get('begin_date', "", type=str)
    begin_time = request.args.get('begin_time', "", type=str)
    begin_time_arrow = arrow.get(f"{begin_date} {begin_time}", 'YYYY-MM-DD HH:mm')
    print("RAW DATE:", begin_date)
    print("RAW TIME:", begin_time)
    print("PARSED TIME:", begin_time_arrow)

    app.logger.debug("km={}".format(km))
    app.logger.debug("request.args: {}".format(request.args))

    open_time = acp_times.open_time(km, brevet_dist_km, begin_time_arrow.isoformat())
    close_time = acp_times.close_time(km, brevet_dist_km, begin_time_arrow.isoformat())
    result = {"open": open_time, "close": close_time}
    return jsonify(result=result)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
