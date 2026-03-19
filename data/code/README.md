# 🕸️ OpenAqua Data Pipeline & Crawlers

This directory contains the automated web crawlers and data processing scripts required to build the foundational knowledge base for the OpenAqua multi-agent system.It strictly follows the data source requirements for building the Case-level and Unit-level databases.

## 🗂️ File Structure & Execution Order

The scripts have been standardized and numbered in the exact sequence they should be executed. 

* **`01_crawl_cases.py`**: Downloads Case-Level PDF/HTML reports from EPA Water Reuse and CWSRF websites into `data/epa_reuse/` and `data/epa_cwsrf/`[cite: 24, 25].
* **`02_crawl_tdb_list.py`**: The first step of Unit-Level data extraction. It intercepts API calls and parses Vue.js instances to extract the complete index of contaminants from the EPA-TDB.
* **`03_crawl_tdb_details.py`**: The core Unit-Level crawler. [cite_start]It iterates through the index generated in step 2 to scrape detailed properties, fate/transport data, and treatment processes for each contaminant, supporting auto-retry and breakpoint continuation[cite: 36, 37, 39, 55].
* [cite_start]**`04_clean_and_taxonomy.py`**: Cleans residual HTML tags from the scraped JSON files and strictly generates the `taxonomy.json` for agent synonym mapping[cite: 109, 110].
* **`05_data_quality_check.py`**: A validation tool that runs a comprehensive integrity check on the generated data directories to ensure no missing fields or corrupted JSON files.

## ⚙️ Prerequisites

These scripts rely on asynchronous web scraping via `Playwright` to bypass dynamic rendering and API obfuscation.

1. Install required Python packages:
   ```bash
   pip install playwright
2. Install the Playwright Chromium browser binary:

   ```bash
   playwright install chromium

## 🚀 How to Run
To build the complete dataset from scratch, execute the scripts sequentially from the root directory of the project:

# Set proxy if required by your network environment
export http_proxy="" && export https_proxy="" 
   ```bash
   # 1. Download EPA Case Studies
   python scripts/01_crawl_cases.py
   # 2. Get the master list of contaminants
   python scripts/02_crawl_tdb_list.py
   # 3. Download detailed JSON data for all contaminants
   python scripts/03_crawl_tdb_details.py
   # 4. Clean HTML tags and build taxonomy.json
   python scripts/04_clean_and_taxonomy.py
   # 5. Verify data integrity
   python scripts/05_data_quality_check.py