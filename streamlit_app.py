import os
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

st.set_page_config(page_title='Chicago Food Safety', layout='wide')

COLORS = {
    'Pass': '#2E8B57',
    'Pass W/ Conditions': '#E69F00',
    'Fail': '#C73E1D',
    'Out Of Business': '#6C757D',
    'No Entry': '#4C78A8',
    'Not Ready': '#9467BD',
}


@st.cache_resource
def get_engine():
    required = ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT']
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f'''Missing environment variables: {', '.join(missing)}''')
    url = URL.create(
        'postgresql+psycopg2',
        username=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        host=os.environ['DB_HOST'],
        port=int(os.environ['DB_PORT']),
        database=os.environ['DB_NAME'],
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def query(sql, params=None):
    with get_engine().connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})


def options(sql, column):
    return query(sql)[column].dropna().astype(str).tolist()


def add_in_filter(conditions, params, column, prefix, values):
    placeholders = []
    for index, value in enumerate(values):
        name = f'{prefix}_{index}'
        placeholders.append(f':{name}')
        params[name] = value
    if placeholders:
        conditions.append(f'''{column} IN ({', '.join(placeholders)})''')


def make_where(filters):
    conditions = ['i.inspection_date BETWEEN :start_date AND :end_date']
    params = {'start_date': filters['start'], 'end_date': filters['end']}
    add_in_filter(conditions, params, 'i.result', 'result', filters['results'])
    add_in_filter(conditions, params, 'i.risk', 'risk', filters['risks'])
    if filters['facility'] != 'All facility types':
        conditions.append('e.facility_type = :facility')
        params['facility'] = filters['facility']
    if filters['zip'] != 'All ZIP codes':
        conditions.append('e.zip = :zip')
        params['zip'] = filters['zip']
    if filters['search']:
        conditions.append('e.name ILIKE :search')
        params['search'] = f'''%{filters['search']}%'''
    return ' AND '.join(conditions), params


st.title('Chicago Food Safety Dashboard')
st.caption(
    'Explore inspection outcomes, locations, violations, and recurring failures. '
    'Risk classification is not the same as an inspection result.'
)

try:
    bounds = query(
        'SELECT MIN(inspection_date) min_date, MAX(inspection_date) max_date FROM inspections'
    ).iloc[0]
    if pd.isna(bounds['min_date']):
        st.warning('The inspections table is empty.')
        st.stop()
    min_date = pd.to_datetime(bounds['min_date']).date()
    max_date = pd.to_datetime(bounds['max_date']).date()
    result_choices = options(
        'SELECT DISTINCT result FROM inspections WHERE result IS NOT NULL ORDER BY result',
        'result',
    )
    risk_choices = options(
        'SELECT DISTINCT risk FROM inspections WHERE risk IS NOT NULL ORDER BY risk',
        'risk',
    )
    facility_choices = options(
        'SELECT DISTINCT facility_type FROM establishments '
        'WHERE facility_type IS NOT NULL ORDER BY facility_type',
        'facility_type',
    )
    zip_choices = options(
        'SELECT DISTINCT zip FROM establishments WHERE zip IS NOT NULL ORDER BY zip',
        'zip',
    )
except Exception as exc:
    st.error('Could not connect to PostgreSQL.')
    st.caption(f'{type(exc).__name__}: {exc}')
    st.info('Start Docker and verify the DB_* variables passed to the app container.')
    st.stop()

with st.sidebar:
    st.header('Filters')
    dates = st.date_input(
        'Inspection date range',
        (min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(dates, (tuple, list)) and len(dates) == 2:
        start_date, end_date = dates
    else:
        start_date = end_date = dates if isinstance(dates, date) else min_date
    selected_results = st.multiselect(
        'Inspection results', result_choices, default=result_choices
    )
    selected_risks = st.multiselect(
        'Risk classifications', risk_choices, default=risk_choices
    )
    facility = st.selectbox('Facility type', ['All facility types', *facility_choices])
    zip_code = st.selectbox('ZIP code', ['All ZIP codes', *zip_choices])
    search = st.text_input(
        'Restaurant name contains', placeholder='Example: Pizza'
    ).strip()
    st.caption('Clear a multiselect to include every value.')

filters = {
    'start': start_date,
    'end': end_date,
    'results': selected_results if 0 < len(selected_results) < len(result_choices) else [],
    'risks': selected_risks if 0 < len(selected_risks) < len(risk_choices) else [],
    'facility': facility,
    'zip': zip_code,
    'search': search,
}
where, params = make_where(filters)
facts = 'FROM inspections i JOIN establishments e ON e.establishment_id = i.establishment_id'

metrics = query(f'''
    SELECT COUNT(*) inspections,
           COUNT(DISTINCT i.establishment_id) establishments,
           100.0 * AVG((LOWER(i.result) = 'pass')::int) pass_rate,
           100.0 * AVG((LOWER(i.result) = 'fail')::int) fail_rate
    {facts} WHERE {where}
''', params).iloc[0]

if int(metrics['inspections']) == 0:
    st.warning('No inspections match these filters.')
    st.stop()

cards = st.columns(4)
cards[0].metric('Inspections', format(int(metrics['inspections']), ','))
cards[1].metric('Establishments', format(int(metrics['establishments']), ','))
cards[2].metric('Pass rate', f'''{float(metrics['pass_rate']):.1f}%''')
cards[3].metric('Fail rate', f'''{float(metrics['fail_rate']):.1f}%''')

geo_tab, trends_tab, violations_tab, repeat_tab = st.tabs(
    ['Geography', 'Trends and comparisons', 'Violations', 'Repeat failures']
)

with geo_tab:
    st.subheader('Where are higher-risk inspection outcomes located?')
    st.caption(
        'Each point is the most recent matching inspection for an establishment. '
        'The map is capped at 5,000 points for responsiveness.'
    )
    map_data = query(f'''
        WITH filtered AS (
            SELECT i.establishment_id, i.inspection_date,
                   COALESCE(i.risk, 'Unknown') risk, i.result,
                   e.name, e.street_address,
                   e.latitude::float latitude, e.longitude::float longitude
            {facts}
            WHERE {where}
              AND e.latitude IS NOT NULL AND e.longitude IS NOT NULL
        ), latest AS (
            SELECT DISTINCT ON (establishment_id) *
            FROM filtered
            ORDER BY establishment_id, inspection_date DESC
        )
        SELECT * FROM latest ORDER BY inspection_date DESC LIMIT 5000
    ''', params)

    if map_data.empty:
        st.info('No mapped establishments match the filters.')
    else:
        map_figure = px.scatter_map(
            map_data,
            lat='latitude',
            lon='longitude',
            color='result',
            color_discrete_map=COLORS,
            hover_name='name',
            hover_data={
                'street_address': True,
                'inspection_date': True,
                'risk': True,
                'latitude': False,
                'longitude': False,
            },
            zoom=9,
            height=560,
        )
        map_figure.update_layout(
            map_style='open-street-map',
            margin={'r': 0, 't': 0, 'l': 0, 'b': 0},
            legend_title_text='Result',
        )
        st.plotly_chart(map_figure, width='stretch')

    st.subheader('Which areas have the highest inspection failure rates?')
    st.caption(
        'ZIP code is a temporary geographic proxy because the current database '
        'does not contain neighborhood or community-area boundaries. '
        'Only ZIP codes with at least five matching inspections are shown.'
    )
    zip_rates = query(f'''
        SELECT COALESCE(NULLIF(e.zip, ''), 'Unknown') zip_code,
               COUNT(*) inspections,
               COUNT(*) FILTER (WHERE LOWER(i.result) = 'fail') failures,
               100.0 * AVG((LOWER(i.result) = 'fail')::int) failure_rate
        {facts} WHERE {where}
        GROUP BY COALESCE(NULLIF(e.zip, ''), 'Unknown')
        HAVING COUNT(*) >= 5
        ORDER BY failure_rate DESC, inspections DESC LIMIT 15
    ''', params)

    if zip_rates.empty:
        st.info('Not enough inspections to calculate area failure rates.')
    else:
        zip_rates['failure_rate'] = zip_rates['failure_rate'].astype(float)
        zip_rates = zip_rates.sort_values('failure_rate')
        zip_figure = px.bar(
            zip_rates,
            x='failure_rate',
            y='zip_code',
            orientation='h',
            text='failure_rate',
            hover_data=['inspections', 'failures'],
            labels={'failure_rate': 'Failure rate (%)', 'zip_code': 'ZIP code'},
        )
        zip_figure.update_traces(
            texttemplate='%{text:.1f}%', textposition='outside', marker_color='#C73E1D'
        )
        st.plotly_chart(zip_figure, width='stretch')


with trends_tab:
    left, right = st.columns(2)

    with left:
        st.subheader('Have inspection outcomes changed over time?')
        monthly = query(f'''
            SELECT DATE_TRUNC('month', i.inspection_date)::date AS inspection_month,
                   100.0 * AVG((LOWER(i.result) = 'pass')::int) pass_rate,
                   100.0 * AVG((LOWER(i.result) = 'fail')::int) fail_rate,
                   100.0 * AVG((LOWER(i.result) LIKE 'pass%condition%')::int) conditional_rate
            {facts} WHERE {where}
            GROUP BY DATE_TRUNC('month', i.inspection_date)
            ORDER BY inspection_month
        ''', params)

        if monthly.empty:
            st.info('No monthly trends match the filters.')
        else:
            monthly['inspection_month'] = pd.to_datetime(monthly['inspection_month'])
            rate_columns = ['pass_rate', 'fail_rate', 'conditional_rate']
            monthly[rate_columns] = monthly[rate_columns].astype(float)
            monthly = monthly.melt(
                id_vars='inspection_month',
                value_vars=rate_columns,
                var_name='outcome',
                value_name='rate',
            )
            monthly['outcome'] = monthly['outcome'].map({
                'pass_rate': 'Pass',
                'fail_rate': 'Fail',
                'conditional_rate': 'Pass with conditions',
            })
            trend_figure = px.line(
                monthly,
                x='inspection_month',
                y='rate',
                color='outcome',
                markers=True,
                color_discrete_map={
                    'Pass': COLORS['Pass'],
                    'Fail': COLORS['Fail'],
                    'Pass with conditions': COLORS['Pass W/ Conditions'],
                },
                labels={
                    'inspection_month': 'Month',
                    'rate': 'Share of inspections (%)',
                    'outcome': 'Outcome',
                },
            )
            st.plotly_chart(trend_figure, width='stretch')

    with right:
        st.subheader('Does risk classification relate to results?')
        risk_results = query(f'''
            SELECT COALESCE(i.risk, 'Unknown') risk,
                   i.result, COUNT(*) inspections
            {facts} WHERE {where}
            GROUP BY COALESCE(i.risk, 'Unknown'), i.result
            ORDER BY risk, result
        ''', params)

        if risk_results.empty:
            st.info('No risk comparison matches the filters.')
        else:
            totals = risk_results.groupby('risk')['inspections'].transform('sum')
            risk_results['percentage'] = 100 * risk_results['inspections'] / totals
            risk_figure = px.bar(
                risk_results,
                x='risk',
                y='percentage',
                color='result',
                color_discrete_map=COLORS,
                barmode='stack',
                hover_data=['inspections'],
                labels={
                    'risk': 'Risk classification',
                    'percentage': 'Inspections (%)',
                    'result': 'Result',
                },
            )
            st.plotly_chart(risk_figure, width='stretch')

    st.subheader('Which facility types fail inspections more frequently?')
    st.caption('Only facility types with at least five matching inspections are shown.')
    facility_rates = query(f'''
        SELECT COALESCE(e.facility_type, 'Unknown') facility_type,
               COUNT(*) inspections,
               COUNT(*) FILTER (WHERE LOWER(i.result) = 'fail') failures,
               100.0 * AVG((LOWER(i.result) = 'fail')::int) failure_rate
        {facts} WHERE {where}
        GROUP BY COALESCE(e.facility_type, 'Unknown')
        HAVING COUNT(*) >= 5
        ORDER BY failure_rate DESC, inspections DESC LIMIT 15
    ''', params)

    if facility_rates.empty:
        st.info('Not enough inspections to compare facility types.')
    else:
        facility_rates['failure_rate'] = facility_rates['failure_rate'].astype(float)
        facility_rates = facility_rates.sort_values('failure_rate')
        facility_figure = px.bar(
            facility_rates,
            x='failure_rate',
            y='facility_type',
            orientation='h',
            text='failure_rate',
            hover_data=['inspections', 'failures'],
            labels={
                'failure_rate': 'Failure rate (%)',
                'facility_type': 'Facility type',
            },
        )
        facility_figure.update_traces(
            texttemplate='%{text:.1f}%', textposition='outside', marker_color='#4C78A8'
        )
        facility_figure.update_layout(height=520)
        st.plotly_chart(facility_figure, width='stretch')


with violations_tab:
    st.subheader('What are the most common food safety violations?')
    st.caption(
        'Counts are distinct inspections containing each violation, not comment rows.'
    )
    violation_counts = query(f'''
        SELECT v.violation_code,
               COALESCE(NULLIF(v.description, ''), 'Description unavailable') violation,
               COUNT(DISTINCT iv.inspection_id) inspections
        FROM inspection_violations iv
        JOIN violations v ON v.violation_code = iv.violation_code
        JOIN inspections i ON i.inspection_id = iv.inspection_id
        JOIN establishments e ON e.establishment_id = i.establishment_id
        WHERE {where}
        GROUP BY v.violation_code, v.description
        ORDER BY inspections DESC LIMIT 10
    ''', params)

    if violation_counts.empty:
        st.info('No recorded violations match the filters.')
    else:
        violation_counts['label'] = (
            violation_counts['violation_code'].astype(str)
            + ' - '
            + violation_counts['violation'].str.slice(0, 70)
        )
        violation_counts = violation_counts.sort_values('inspections')
        violation_figure = px.bar(
            violation_counts,
            x='inspections',
            y='label',
            orientation='h',
            text='inspections',
            hover_data={
                'violation': True,
                'violation_code': True,
                'label': False,
            },
            labels={'inspections': 'Inspections', 'label': 'Violation'},
        )
        violation_figure.update_traces(
            marker_color='#E69F00', textposition='outside'
        )
        violation_figure.update_layout(height=600)
        st.plotly_chart(violation_figure, width='stretch')


with repeat_tab:
    st.subheader('Which establishments repeatedly fail inspections?')
    st.caption(
        'Establishments shown have at least two failed inspections within the filters.'
    )
    repeat_failures = query(f'''
        SELECT e.name restaurant, e.street_address address, e.zip zip_code,
               COUNT(DISTINCT i.inspection_id) failed_inspections,
               MIN(i.inspection_date) first_failure,
               MAX(i.inspection_date) latest_failure
        {facts}
        WHERE {where} AND LOWER(i.result) = 'fail'
        GROUP BY e.establishment_id, e.name, e.street_address, e.zip
        HAVING COUNT(DISTINCT i.inspection_id) >= 2
        ORDER BY failed_inspections DESC, latest_failure DESC LIMIT 250
    ''', params)

    if repeat_failures.empty:
        st.info('No establishments have multiple failures within the filters.')
    else:
        repeat_failures = repeat_failures.rename(columns={
            'restaurant': 'Restaurant',
            'address': 'Address',
            'zip_code': 'ZIP Code',
            'failed_inspections': 'Failed Inspections',
            'first_failure': 'First Failure',
            'latest_failure': 'Latest Failure',
        })
        st.dataframe(
            repeat_failures,
            width='stretch',
            hide_index=True,
            column_config={
                'Failed Inspections': st.column_config.NumberColumn(format='%d'),
                'First Failure': st.column_config.DateColumn(format='MMM D, YYYY'),
                'Latest Failure': st.column_config.DateColumn(format='MMM D, YYYY'),
            },
        )

st.divider()
st.caption(
    'Source: City of Chicago Food Inspections. '
    'Rates use inspections, not unique restaurants, as the denominator.'
)
