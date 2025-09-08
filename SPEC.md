# **Project Specification: Aviation Anomaly Tracker**

## **1. Overview & Vision**

This document outlines the requirements for building an interactive web-based visualization tool to analyze the rate of aviation emergencies over time and space.

The primary goal is to move beyond real-time alerting and provide a strategic tool for identifying geographic hotspots where the *proportion* of flights experiencing an emergency is unusually high. The final product will be an interactive map that is fast, intuitive, and data-rich, allowing users to explore both high-level trends and drill down into specific incident details.

### **User Stories**

* As an aviation analyst, I want to see a map of incident rates so I can identify regions with potential underlying safety or operational issues.
* As a user, I want to filter the map by time so I can understand how patterns evolve seasonally or in response to events.
* As a user, I want to zoom into the map to see more granular detail for a specific area.
* As a user, I want to click on a hotspot to see a list of the specific incidents that occurred there.

## **2. System Architecture**

The system is composed of two main parts: an offline data processing pipeline and a web-based frontend. This architecture is designed for performance, simplicity, and maintainability.

### **2.1. Backend: Data Processing Pipeline**

* **Trigger:** A scheduled batch job (e.g., daily Cron job or Airflow DAG).
* **Data Source:** OpenSky Network's Trino database (states\_history\_data4 and flights\_data4 tables).
* **Processing Engine:** A Python script orchestrating **DuckDB** queries. All data transformation will be performed within DuckDB using its native SQL capabilities and the official **H3 extension**. No Pandas or GeoPandas will be used.
* **Storage Format:** Apache Parquet.

### **2.2. Frontend: Interactive Map**

* **Framework:** **HTMX** for server-driven interactivity and **pure JavaScript** for client-side enhancements. No complex build scripts, transpilation, or frontend frameworks (React, Vue, etc.) are required.
* **Mapping Library:** A library capable of handling vector tiles and WebGL rendering for performance (e.g., Mapbox GL JS, Deck.gl).
* **Hexagonal Grid:** Uber's H3 library will be used for all geographic grid logic, accessed via the DuckDB extension in the backend.

## **3. Data Processing Pipeline (ETL)**

This pipeline is a **two-stage process** to isolate expensive queries from iterative data transformation.

### **3.1. Staged Execution & Caching**

* **Stage 1 (Extraction):** A dedicated script to query raw data from Trino for a specified date range and save it directly to a local Parquet cache. This is the only stage that communicates with OpenSky.
* **Stage 2 (Transformation):** A separate script that reads exclusively from the local raw Parquet cache. It uses DuckDB to perform all transformations (incident grouping, H3 calculations, normalization). This stage can be re-run frequently without network cost.

### **3.2. Stage 1: Raw Data Extraction & Caching**

* The script will accept a start and end date range.
* It will query the opensky.states\_history\_data4 table for all state vectors within this range.
* The raw, unprocessed results will be saved directly to monthly Parquet files.

### **3.3. Stage 2: Transformation & Aggregation (DuckDB Only)**

* This stage reads data **only from the raw Parquet cache** using DuckDB.
* **Incident Definition:** A SQL query will filter for emergency squawks (7700, 7600, 7500\) and group them into unique incidents. A single "incident" is defined by grouping squawks from the same icao24 within a **configurable 3-hour window**.
* **Enrichment:** Each unique incident is enriched with flight details by joining with the opensky.flights\_data4 table.
* **H3 Grid Calculation:** DuckDB's H3 extension functions (h3\_latlng\_to\_cell) will be used to calculate H3 cell indexes for each incident and flight path at multiple resolutions (e.g., 1 through 7).
* **Aggregation:** A final SQL query will calculate the incident counts and total flight counts for every H3 cell at each resolution level.

### **3.4. Data Storage**

* **Raw Data Cache (Stage 1 Output):** Stores direct results from Trino.
  * **File Path:** /data/raw\_states/{YYYYMM}.parquet.
* **Processed Aggregates (Stage 2 Output):** Stores frontend-ready data.
  * **File Path:** /data/h3\_aggregates/{YYYYMM}-{resolution}.parquet.

## **4. Frontend & User Experience**

### **4.1. Map Visualization**

* The map displays a hexagonal grid colored by the **Normalized Incident Rate**.
* **Rate Calculation:** (COUNT(Incidents in Hex) / COUNT(Total Flights in Hex)) \* 100,000.
* **Color Scale:** A perceptually uniform color scale (e.g., Blue \-\> Yellow \-\> Red).
* **"No Data" Color:** Hexagons with Total Flights \= 0 are rendered in a distinct, neutral color (e.g., light gray).

### **4.2. Interactivity**

* **Dynamic Resolution:** The H3 grid resolution automatically updates based on the map's zoom level.
* **Time Slider:** A slider allows users to select a month/year. The map updates by querying the relevant monthly Parquet files.
* **Drill-Down:** Clicking a hexagon opens a sortable table of incidents.
  * **Columns:** Date, Time (UTC), Callsign, Aircraft Type, Origin, Destination, Squawk Code.

## **5. Error Handling Strategy**

The system will **fail fast and hard**. Errors in the data pipeline must terminate the process and alert a human.

* **Pipeline Failures:** The ETL script MUST terminate and raise an explicit exception if:
  * Connection to OpenSky Trino fails.
  * OpenSky returns an empty or malformed dataset.
  * Writing a Parquet file fails.
  * A DuckDB query fails.
* **Frontend Errors:** Gracefully handle missing Parquet files with a user-friendly message.

## **6. Testing Plan**

### **6.1. Guiding Principles**

* **Test-Driven Development (TDD):** All data transformation logic, which lives in SQL, must be designed and built using a test-first approach.
* **Clean Code:** Both the orchestrating Python code and the SQL queries must be simple, readable, and maintainable.

### **6.2. The TDD Cycle for SQL Logic (Red-Green-Refactor)**

The development of DuckDB queries must follow this cycle:

1. **Red:** Write a Python test that runs a DuckDB query against a small, hand-crafted Parquet input file. Assert the expected outcome. This test will fail initially because the query is not yet implemented.
2. **Green:** Write the simplest possible SQL query to make the test pass.
3. **Refactor:** Improve the SQL for clarity and efficiency without breaking the test. Add a new failing test for another edge case and repeat the cycle.

### **6.3. Clean Code for SQL & Python**

* **SQL Readability:** Complex queries must be broken into logical steps using **Common Table Expressions (CTEs)** with descriptive names. The logic should be stored in well-commented .sql files.
* **Python Orchestration:** The Python scripts should act as simple orchestrators. Their role is to execute the .sql files with the correct parameters (input/output paths, dates) and handle errors. They should not contain complex data manipulation logic.

### **6.4. Specific Test Cases (Unit & Integration)**

* **Incident Grouping:** Verify that mock state vectors are correctly grouped into a single incident, especially across the 3-hour window boundary.
* **H3 Calculation:** Confirm a lat/lon coordinate is assigned to the correct H3 cell ID.
* **Rate Normalization:** Ensure the final rate calculation is accurate given a known set of inputs.
* **End-to-End Pipeline:** An integration test using a small, local dataset to run the full pipeline from raw cache to final H3 aggregate.
* **Frontend Integration:** A test to ensure the frontend can load a sample aggregate Parquet file and render data.

### **6.5. Phased Rollout Plan**

1. **Phase 1 (Walking Skeleton):** Implement the full data pipeline for a single month and a single, fixed H3 resolution. The frontend will be a static map.
2. **Phase 2 (Interactivity):** Implement the time slider.
3. **Phase 3 (Dynamic Grid):** Implement the dynamic zoom-level loading.
