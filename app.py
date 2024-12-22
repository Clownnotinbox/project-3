from flask import Flask, render_template, request, session, jsonify
import requests
import os
from dotenv import load_dotenv
from flask_caching import Cache
import logging
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

cache = Cache(app, config={"CACHE_TYPE": "simple"})

API_KEY = os.getenv("ACCUWEATHER_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_location_key_by_city(city):
    params = {"apikey": API_KEY, "q": city}
    try:
        response = requests.get(
            "https://dataservice.accuweather.com/locations/v1/cities/search",
            params=params,
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        if data:
            return data[0].get("Key")
        else:
            return None
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error при запросе locationKey для города {city}: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Ошибка соединения при запросе locationKey для города {city}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Тайм-аут при запросе locationKey для города {city}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Произошла ошибка при запросе locationKey для города {city}: {req_err}")
    return None


def check_bad_weather(temperature, wind_speed, precipitation_probability):
    conditions = []
    if temperature < -15 or temperature > 35:
        conditions.append("Температура слишком низкая или высокая")
    if wind_speed > 50:
        conditions.append("Сильный ветер")
    if precipitation_probability > 60:
        conditions.append("Высокая вероятность осадков")
    
    if conditions:
        return "Плохие погодные условия: " + ", ".join(conditions)
    return "Хорошие погодные условия"


@cache.memoize(timeout=3600)
def get_weather(location_key, days=5):
    url = f"https://dataservice.accuweather.com/forecasts/v1/daily/{days}day/{location_key}"
    params = {"apikey": API_KEY, "details": "true", "metric": "true"}
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        forecasts = data.get("DailyForecasts", [])
        
        weather_data = []
        for forecast in forecasts:
            day_weather = {
                "date": forecast.get("Date", "N/A")[:10],
                "temperature_max": forecast.get("Temperature", {}).get("Maximum", {}).get("Value", "N/A"),
                "temperature_min": forecast.get("Temperature", {}).get("Minimum", {}).get("Value", "N/A"),
                "wind_speed": forecast.get("Day", {}).get("Wind", {}).get("Speed", {}).get("Value", "N/A"),
                "precipitation_probability": forecast.get("Day", {}).get("PrecipitationProbability", "N/A"),
                "weather_condition": check_bad_weather(
                    forecast.get("Temperature", {}).get("Maximum", {}).get("Value", 0),
                    forecast.get("Day", {}).get("Wind", {}).get("Speed", {}).get("Value", 0),
                    forecast.get("Day", {}).get("PrecipitationProbability", 0)
                ),
            }
            weather_data.append(day_weather)
        
        return weather_data
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error при запросе погоды для locationKey {location_key}: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Ошибка соединения при запросе погоды для locationKey {location_key}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Тайм-аут при запросе погоды для locationKey {location_key}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Произошла ошибка при запросе погоды для locationKey {location_key}: {req_err}")
    return None


@app.route("/", methods=["GET", "POST"])
def index():
    weather = []
    if request.method == "POST":
        start_city = request.form.get("start_city")
        end_city = request.form.get("end_city")
        intermediate_cities = request.form.getlist("intermediate_cities[]")
        days = request.form.get("days", 5)
        days = int(days) if days.isdigit() else 5

        all_cities = [start_city] + intermediate_cities + [end_city]

        if all_cities and start_city and end_city:
            try:
                weather_points = []
                for city in all_cities:
                    location_key = get_location_key_by_city(city)
                    if not location_key:
                        weather = {
                            "error": f'Город "{city}" не найден. Проверьте правильность названия.'
                        }
                        return render_template("index.html", weather=weather)
                    weather_data = get_weather(location_key, days=days)
                    if not weather_data:
                        weather = {
                            "error": f'Не удалось получить данные о погоде для города "{city}".'
                        }
                        return render_template("index.html", weather=weather)
                    weather_points.append({
                        "city": city,
                        "weather": weather_data
                    })
                
                session['weather'] = weather_points
                session['days'] = days

                weather = weather_points

            except Exception as e:
                logger.error(f"Ошибка при обработке запроса: {e}")
                weather = {
                    "error": "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."
                }
    return render_template("index.html", weather=weather)


@app.route("/api/weather")
def get_weather_api():
    weather = session.get('weather')
    days = session.get('days', 5)
    if not weather:
        return jsonify({"error": "No weather data available."}), 400
    return jsonify({"weather": weather, "days": days}), 200


dash_app = dash.Dash(
    __name__,
    server=app,
    url_base_pathname='/dash/',
    external_stylesheets=['https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css']
)


def create_dash_layout():
    if has_request_context():
        weather = session.get('weather')
        days = session.get('days', 5)
        if weather:
            options = [{'label': point['city'], 'value': point['city']} for point in weather]
        else:
            options = []
    else:
        weather = None
        days = 5
        options = []
    
    return html.Div([
        html.H1("Визуализация прогноза погоды", style={'textAlign': 'center', 'color': '#4169E1'}),
        dcc.Dropdown(
            id='city-dropdown',
            options=options,
            value=options[0]['value'] if options else None,
            style={'width': '50%', 'margin': 'auto', 'marginBottom': '20px'}
        ),
        dcc.Graph(id='temperature-graph'),
        dcc.Graph(id='precipitation-graph')
    ], className='container')


dash_app.layout = create_dash_layout


@dash_app.callback(
    [Output('temperature-graph', 'figure'),
     Output('precipitation-graph', 'figure'),
     Output('city-dropdown', 'options')],
    [Input('city-dropdown', 'value')]
)
def update_graphs(selected_city):
    if not selected_city:
        return go.Figure(), go.Figure(), []
    
    try:
        from flask import request
        base_url = request.host_url.rstrip('/')
        api_url = f"{base_url}/api/weather"
        response = requests.get(api_url)
        if response.status_code != 200:
            return go.Figure(), go.Figure(), []
        data = response.json()
        weather = data.get('weather')
        days = data.get('days', 5)
    except:
        return go.Figure(), go.Figure(), []
    
    options = [{'label': point['city'], 'value': point['city']} for point in weather]
    
    if selected_city not in [point['city'] for point in weather]:
        return go.Figure(), go.Figure(), options
    
    city_weather = next((point['weather'] for point in weather if point['city'] == selected_city), [])
    
    if not city_weather:
        return go.Figure(), go.Figure(), options
    
    dates = [day['date'] for day in city_weather]
    temps_max = [day['temperature_max'] for day in city_weather]
    temps_min = [day['temperature_min'] for day in city_weather]
    precipitation = [day['precipitation_probability'] for day in city_weather]
    
    temp_fig = go.Figure()
    temp_fig.add_trace(go.Scatter(
        x=dates,
        y=temps_max,
        mode='lines+markers',
        name='Максимальная температура',
        line=dict(color='#FF5733')
    ))
    temp_fig.add_trace(go.Scatter(
        x=dates,
        y=temps_min,
        mode='lines+markers',
        name='Минимальная температура',
        line=dict(color='#33C1FF')
    ))
    temp_fig.update_layout(
        title=f'Прогноз температуры для {selected_city}',
        xaxis_title='Дата',
        yaxis_title='Температура (°C)',
        template='plotly_white'
    )

    precip_fig = go.Figure()
    precip_fig.add_trace(go.Bar(
        x=dates,
        y=precipitation,
        name='Вероятность осадков',
        marker_color='#42f44b'
    ))
    precip_fig.update_layout(
        title=f'Вероятность осадков для {selected_city}',
        xaxis_title='Дата',
        yaxis_title='Вероятность осадков (%)',
        template='plotly_white'
    )
    
    return temp_fig, precip_fig, options


if __name__ == "__main__":
    app.run(debug=True)
