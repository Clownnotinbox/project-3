from flask import Flask, render_template, request, session, jsonify, has_request_context
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
# Убедитесь, что API_KEY корректно загружен
if not API_KEY:
    raise ValueError("Не найден API-ключ AccuWeather. Проверьте файл .env.")

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
            location = data[0]
            return {
                "Key": location.get("Key"),
                "LocalizedName": location.get("LocalizedName"),
                "Latitude": location.get("GeoPosition", {}).get("Latitude"),
                "Longitude": location.get("GeoPosition", {}).get("Longitude")
            }
        else:
            return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Ошибка при запросе locationKey для города {city}: {req_err}")
        return {"error": f"Ошибка при поиске города '{city}': {str(req_err)}"}

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
        try:
            error_detail = http_err.response.json()
            error_message = error_detail.get("Message", str(http_err))
        except ValueError:
            error_message = http_err.response.text or str(http_err)
        return {"error": f"HTTP error: {http_err.response.status_code} {error_message}"}
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Ошибка при запросе погоды для locationKey {location_key}: {req_err}")
        return {"error": f"Ошибка запроса: {str(req_err)}"}

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
                    location = get_location_key_by_city(city)
                    if location is None:
                        weather = {
                            "error": f'Город "{city}" не найден. Проверьте правильность названия.'
                        }
                        return render_template("index.html", weather=weather)
                    if isinstance(location, dict) and "error" in location:
                        weather = {
                            "error": location["error"]
                        }
                        return render_template("index.html", weather=weather)
                    
                    weather_data = get_weather(location["Key"], days=days)
                    if isinstance(weather_data, dict) and "error" in weather_data:
                        weather = {
                            "error": f'Не удалось получить данные о погоде для города "{city}": {weather_data["error"]}'
                        }
                        return render_template("index.html", weather=weather)
                    if not weather_data:
                        weather = {
                            "error": f'Не удалось получить данные о погоде для города "{city}".'
                        }
                        return render_template("index.html", weather=weather)
                    
                    weather_points.append({
                        "city": location["LocalizedName"],
                        "latitude": location["Latitude"],
                        "longitude": location["Longitude"],
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
        dcc.Graph(id='precipitation-graph'),
        dcc.Graph(id='map-graph'),
        html.Div([
            dcc.Checklist(
                id='weather-parameters',
                options=[
                    {'label': 'Максимальная температура', 'value': 'temperature_max'},
                    {'label': 'Минимальная температура', 'value': 'temperature_min'},
                    {'label': 'Скорость ветра', 'value': 'wind_speed'},
                    {'label': 'Вероятность осадков', 'value': 'precipitation_probability'}
                ],
                value=['temperature_max', 'temperature_min', 'wind_speed', 'precipitation_probability'],
                labelStyle={'display': 'inline-block', 'margin-right': '10px'}
            )
        ], style={'textAlign': 'center', 'marginTop': '20px'})
    ], className='container')

dash_app.layout = create_dash_layout

@dash_app.callback(
    [Output('temperature-graph', 'figure'),
     Output('precipitation-graph', 'figure'),
     Output('map-graph', 'figure'),
     Output('city-dropdown', 'options')],
    [Input('city-dropdown', 'value'),
     Input('weather-parameters', 'value')]
)
def update_graphs(selected_city, selected_parameters):
    if not selected_city:
        return go.Figure(), go.Figure(), go.Figure(), []
    
    try:
        from flask import request
        base_url = request.host_url.rstrip('/')
        api_url = f"{base_url}/api/weather"
        response = requests.get(api_url)
        if response.status_code != 200:
            logger.error(f"Ошибка при получении данных из API: {response.status_code} {response.text}")
            return go.Figure(), go.Figure(), go.Figure(), []
        data = response.json()
        weather = data.get('weather')
        days = data.get('days', 5)
    except Exception as e:
        logger.error(f"Ошибка при запросе API: {e}")
        return go.Figure(), go.Figure(), go.Figure(), []
    
    options = [{'label': point['city'], 'value': point['city']} for point in weather]
    
    if selected_city not in [point['city'] for point in weather]:
        return go.Figure(), go.Figure(), go.Figure(), options
    
    city_data = next((point for point in weather if point['city'] == selected_city), {})
    city_weather = city_data.get('weather', [])
    latitude = city_data.get('latitude')
    longitude = city_data.get('longitude')
    
    dates = [day['date'] for day in city_weather]
    temps_max = [day['temperature_max'] for day in city_weather]
    temps_min = [day['temperature_min'] for day in city_weather]
    precipitation = [day['precipitation_probability'] for day in city_weather]
    wind_speed = [day['wind_speed'] for day in city_weather]
    
    temperature_traces = []
    if 'temperature_max' in selected_parameters:
        temperature_traces.append(go.Scatter(
            x=dates,
            y=temps_max,
            mode='lines+markers',
            name='Максимальная температура',
            line=dict(color='#FF5733'),
            hoverinfo='x+y'
        ))
    if 'temperature_min' in selected_parameters:
        temperature_traces.append(go.Scatter(
            x=dates,
            y=temps_min,
            mode='lines+markers',
            name='Минимальная температура',
            line=dict(color='#33C1FF'),
            hoverinfo='x+y'
        ))
    
    temp_fig = go.Figure(data=temperature_traces)
    temp_fig.update_layout(
        title=f'Прогноз температуры для {selected_city}',
        xaxis_title='Дата',
        yaxis_title='Температура (°C)',
        template='plotly_white',
        hovermode='closest'
    )
    
    precip_trace = go.Bar(
        x=dates,
        y=precipitation,
        name='Вероятность осадков',
        marker_color='#42f44b',
        hoverinfo='x+y'
    )
    precip_fig = go.Figure(data=[precip_trace])
    precip_fig.update_layout(
        title=f'Вероятность осадков для {selected_city}',
        xaxis_title='Дата',
        yaxis_title='Вероятность осадков (%)',
        template='plotly_white',
        hovermode='closest'
    )
    
    # Создание маршрута на карте
    latitudes = [point['latitude'] for point in weather]
    longitudes = [point['longitude'] for point in weather]
    city_names = [point['city'] for point in weather]
    weather_conditions = [point['weather'][-1]['weather_condition'] for point in weather]
    
    # Добавление линии маршрута
    route_trace = go.Scattermapbox(
        lat=latitudes,
        lon=longitudes,
        mode='markers+lines',
        marker=go.scattermapbox.Marker(
            size=10,
            color='#FF5733'
        ),
        line=go.scattermapbox.Line(
            width=2,
            color='#1f78b4'
        ),
        text=[f"{city}: {condition}" for city, condition in zip(city_names, weather_conditions)],
        hoverinfo='text',
        name='Маршрут'
    )
    
    # Создание фигуры карты
    map_fig = go.Figure(data=[route_trace])
    map_fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=latitude, lon=longitude),
            zoom=5
        ),
        margin={"r":0,"t":0,"l":0,"b":0},
        hovermode='closest'
    )
    
    return temp_fig, precip_fig, map_fig, options

if __name__ == "__main__":
    app.run(debug=True)
