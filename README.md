# Chicago Food Inspections

DAEN 328 term project: an ETL pipeline, PostgreSQL database, and Streamlit dashboard for Chicago food-inspection data.

## Run the project

1. Start Docker Desktop.
2. Create the local environment file:

   ```powershell
   Copy-Item .env.sample .env
   ```

3. Open `.env` and replace both `REPLACE_ME` values with the same local development password. The `.env` file is ignored by Git and must not be committed.
4. Build and start the stack:

   ```powershell
   docker compose up --build
   ```

5. After the ETL service finishes, open <http://localhost:8501>.
6. Stop the services with `Ctrl+C`, then run `docker compose down`.

To remove the PostgreSQL volume and reload all data from scratch, use `docker compose down -v`. This permanently deletes the local project database.

## Database structure

The database contains five tables: establishments, inspections, violations, inspection_violations and etl_watermark. The ER Diagram for the database is shown below.

![Database ERD](images/database-erd.png)

## Dashboard questions

The dashboard filters by date, result, risk classification, facility type, ZIP code, and restaurant name. It answers:

1. Where are establishments with higher food-safety risks or failed results located?
2. Which geographic areas have the highest inspection failure rates?
3. Have pass, fail, and conditional-pass rates changed over time?
4. What are the most common violations?
5. How do inspection outcomes differ by risk classification?
6. Which establishments repeatedly fail inspections?
7. Which facility types have higher failure rates?

The current database does not contain Chicago neighborhood or community-area boundaries. Until a spatial lookup is added to the ETL, the area comparison uses ZIP code and labels it as a proxy.
