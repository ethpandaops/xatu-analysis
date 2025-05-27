# Gas Usage Performance Analysis Documentation

## Overview

The `gas_block_arrival.ipynb` notebook analyzes the relationship between gas usage and block arrival times in Ethereum networks. This document provides a detailed technical breakdown of how the analysis works, focusing on the data collection methods, transformations, and presentation techniques.

## 1. Data Collection

### 1.1 Database Connection Setup

The notebook establishes a connection to ClickHouse using SQLAlchemy:

```python
db_url = f"clickhouse+http://{username}:{password}@{host}:443/default?protocol=https"
engine = create_engine(db_url)
connection = engine.connect()
```

**Configuration Sources:**
- Environment variables loaded via `python-dotenv`
- Default values provided as fallbacks
- Key parameters: `CLICKHOUSE_HOST`, `CLICKHOUSE_USERNAME`, `CLICKHOUSE_PASSWORD`, `NETWORK`
- Analysis periods: `START_DATE_1/END_DATE_1` and `START_DATE_2/END_DATE_2`

### 1.2 Block Arrival Data Collection

**Function:** `fetch_block_arrival_times(network, start_date, end_date)`

**Source Table:** `beacon_api_eth_v1_events_block_gossip`

**SQL Query Structure:**
```sql
SELECT
    slot,
    slot_start_date_time,
    propagation_slot_start_diff as arrival_time,
    meta_client_name,
    meta_consensus_implementation,
    meta_client_geo_continent_code,
    block as block_root
FROM beacon_api_eth_v1_events_block_gossip FINAL
WHERE
    meta_network_name = :network
    AND slot_start_date_time BETWEEN :start_date AND :end_date
    AND meta_client_name != ''
    AND meta_client_name IS NOT NULL
    AND meta_consensus_implementation != ''
    AND meta_consensus_implementation IS NOT NULL
    AND propagation_slot_start_diff < 12000  -- Filter outliers > 12 seconds
```

**Data Points Collected:**
- Block gossip propagation times (how long it takes for block gossip to reach each client)
- Client metadata (name, consensus implementation, geographic location)
- Slot timing information
- Block identifiers

**Filtering Logic:**
- Excludes records with missing client metadata
- Removes extreme outliers (>12 second propagation times)
- Uses `FINAL` modifier for ClickHouse deduplication

### 1.3 Head Time Data Collection

**Function:** `fetch_head_time_data(network, start_date, end_date)`

**Source Tables:** 
- `beacon_api_eth_v1_events_head`
- `beacon_api_eth_v1_events_block` 
- `beacon_api_eth_v1_events_blob_sidecar`

**Complex Query Structure:**
The query uses Common Table Expressions (CTEs) to:

1. **Head Events CTE:** Collects head event propagation times
2. **Block Events CTE:** Collects block event propagation times  
3. **Blob Events CTE:** Collects blob sidecar event propagation times (aggregated by MAX per slot)
4. **Union and Aggregation:** Combines all events and takes the maximum propagation time per slot/client combination

**Key Logic:**
```sql
SELECT
    slot,
    slot_start_date_time,
    MAX(arrival_time) as head_time,
    meta_client_name,
    meta_consensus_implementation,
    meta_client_geo_continent_code
FROM all_events
GROUP BY slot, slot_start_date_time, meta_client_name, 
         meta_consensus_implementation, meta_client_geo_continent_code
```

**Purpose:** Head time represents the maximum time across all event types (head, block, blob) to reach a client, providing a comprehensive view of when a client has "fully processed" a slot.

### 1.4 Execution/Gas Data Collection

**Function:** `fetch_execution_data(network, start_date, end_date)`

**Source Table:** `beacon_api_eth_v2_beacon_block`

**SQL Query:**
```sql
SELECT
    slot,
    slot_start_date_time,
    execution_payload_block_number,
    execution_payload_gas_used
FROM canonical_beacon_block FINAL
WHERE
    meta_network_name = :network
    AND slot_start_date_time BETWEEN :start_date AND :end_date
    AND execution_payload_block_number IS NOT NULL
```

**Data Retrieved:**
- Gas usage per execution block
- Execution block numbers
- Slot timing alignment with beacon chain

## 2. Data Transformation

### 2.1 DataFrame Creation and Cleaning

**Process Flow:**
1. **Raw Data to DataFrames:** Convert SQL results to pandas DataFrames with proper column naming
2. **Data Type Conversion:**
   ```python
   block_df['arrival_time'] = pd.to_numeric(block_df['arrival_time'], errors='coerce')
   head_time_df['head_time'] = pd.to_numeric(head_time_df['head_time'], errors='coerce')
   gas_df['execution_payload_gas_used'] = pd.to_numeric(gas_df['execution_payload_gas_used'], errors='coerce')
   ```
3. **Timestamp Parsing:**
   ```python
   block_df['slot_start_date_time'] = pd.to_datetime(block_df['slot_start_date_time'])
   ```

### 2.2 Data Merging Strategy

**Multi-step Join Process:**
1. **Primary Join:** Block gossip data + Head time data
   ```python
   combined_df = pd.merge(
       block_df,
       head_time_df[['slot', 'meta_client_name', 'head_time']],
       on=['slot', 'meta_client_name'],
       how='inner'
   )
   ```

2. **Secondary Join:** Combined data + Gas metrics
   ```python
   combined_df = pd.merge(
       combined_df,
       gas_df[['slot', 'execution_payload_gas_used']],
       on='slot',
       how='inner'
   )
   ```

**Join Key Logic:**
- Block gossip ↔ Head time: Joined on `slot` + `meta_client_name` (client-specific timing)
- Combined ↔ Gas data: Joined on `slot` only (gas usage is per-slot, not per-client)

**Column Renaming:**
```python
combined_df = combined_df.rename(columns={
    'arrival_time': 'block_gossip_time',
    'execution_payload_gas_used': 'gas_used'
})
```

### 2.3 Time Bucketing Implementation

**Function:** `create_time_buckets(df, num_buckets=30)`

**Algorithm:**
1. **Calculate Time Range:**
   ```python
   min_time = df['slot_start_date_time'].min()
   max_time = df['slot_start_date_time'].max()
   time_range = max_time - min_time
   bucket_size = time_range / num_buckets
   ```

2. **Create Bucket Edges:**
   ```python
   bucket_edges = [min_time + i * bucket_size for i in range(num_buckets + 1)]
   ```

3. **Assign Data to Buckets:**
   ```python
   df['time_bucket'] = pd.cut(
       df['slot_start_date_time'], 
       bins=bucket_edges,
       labels=[f"Bucket {i+1}" for i in range(num_buckets)]
   )
   ```

4. **Add Bucket Metadata:**
   ```python
   bucket_start_times = {f"Bucket {i+1}": bucket_edges[i] for i in range(num_buckets)}
   df['bucket_start_time'] = df['time_bucket'].map(bucket_start_times)
   ```

**Purpose:** Creates 30 equal-duration time windows for temporal analysis, enabling trend detection over time.

### 2.4 Statistical Calculations

**Consensus Implementation Analysis:**
```python
consensus_metrics = df.groupby('meta_consensus_implementation').agg({
    'block_gossip_time': ['count', 'mean', 'median', lambda x: np.percentile(x, 95)],
    'gas_used': ['mean', 'median']
}).sort_values(('block_gossip_time', 'count'), ascending=False)
```

**Time-Bucketed Metrics:**
```python
time_metrics = df.groupby('time_bucket').agg({
    'gas_used': ['mean', 'median', 'min', 'max'],
    'block_gossip_time': ['mean', 'median', 'min', 'max', lambda x: np.percentile(x, 95)],
    'head_time': ['mean', 'median', 'min', 'max', lambda x: np.percentile(x, 95)],
    'bucket_start_time': 'first'
})
```

**Time Difference Analysis:**
```python
all_data['time_difference'] = all_data['head_time'] - all_data['block_gossip_time']
```

## 3. Data Presentation

### 3.1 Visualization Framework

**Core Plotting Setup:**
```python
plt.style.use('ggplot')
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['figure.dpi'] = 100
```

**Custom Branding Function:**
The `add_branding()` function creates a composite figure with:
- Header area for logos and titles
- Content area for the actual plot
- Automated logo placement from `../../assets/content/` directory
- Fallback to text-based branding if images unavailable

### 3.2 Scatter Plot Analysis

**Gas Usage vs Block Gossip Time:**
```python
scatter = ax.scatter(
    df['gas_used'], 
    df['block_gossip_time'],
    alpha=0.4,
    s=10,
    c=df['slot_start_date_time'],  # Color-coded by time
    cmap='viridis'
)
```

**Trend Line Addition:**
```python
from scipy.stats import linregress
slope, intercept, r_value, p_value, std_err = linregress(
    df.loc[mask, 'gas_used'], 
    df.loc[mask, 'block_gossip_time']
)
x_range = np.linspace(df['gas_used'].min(), df['gas_used'].max(), 100)
ax.plot(x_range, slope * x_range + intercept, 'r--', 
        label=f'Trend: y={slope:.7f}x+{intercept:.2f}, r²={r_value**2:.2f}')
```

**Correlation Display:**
```python
corr = df[['gas_used', 'block_gossip_time']].corr().iloc[0, 1]
ax.annotate(f'Correlation: {corr:.4f}', xy=(0.05, 0.95), xycoords='axes fraction')
```

### 3.3 Multi-Axis Time Series Plots

**Dual Y-Axis Implementation:**
```python
fig, ax1 = plt.subplots(figsize=(16, 8))

# Primary axis: Gas usage
ax1.plot(time_metrics.index, time_metrics[('gas_used', 'mean')], 
         color='tab:blue', marker='o', label='Mean Gas Used')
ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x/1e6:.1f}M'))

# Secondary axis: Arrival times
ax2 = ax1.twinx()
ax2.plot(time_metrics.index, time_metrics[('block_gossip_time', 'mean')], 
         color='tab:red', marker='s', label='Mean Block Gossip Time')
```

### 3.4 Heatmap Visualization

**2D Histogram Creation:**
```python
heatmap, xedges, yedges = np.histogram2d(
    all_data['gas_used'].clip(upper=max_gas), 
    all_data['block_gossip_time'].clip(upper=max_arrival),
    bins=[gas_bins, arrival_bins]
)

# Log transformation for better visibility
heatmap = np.log1p(heatmap.T)

im = ax.imshow(
    heatmap, 
    extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]], 
    origin='lower', 
    aspect='auto',
    cmap='viridis'
)
```

### 3.5 Box Plot Analysis

**Gas Range Bucketing:**
```python
# Create fixed 5M chunk bins
gas_bins = list(range(min_gas_rounded, max_gas_rounded + 5_000_000, 5_000_000))
gas_bin_labels = [f"{i//1_000_000}-{(i+5_000_000)//1_000_000}M" for i in gas_bins[:-1]]

all_data['gas_range'] = pd.cut(
    all_data['gas_used'], 
    bins=gas_bins,
    labels=gas_bin_labels
)
```

**Box Plot Generation:**
```python
boxplot = ax.boxplot(
    non_empty_data,
    patch_artist=True,
    notch=True,
    showfliers=False,  # Hide outliers to reduce noise
    widths=0.6
)
```

### 3.6 Consensus Implementation Comparison

**Implementation Filtering:**
```python
# Get top implementations by count
top_implementations = all_data['meta_consensus_implementation'].value_counts().head(6).index.tolist()
filtered_data = all_data[all_data['meta_consensus_implementation'].isin(top_implementations)]
```

**Binned Trend Analysis:**
```python
# Bin the data by gas to create smoother trend lines
n_bins = 15
gas_bins = pd.cut(impl_data['gas_used'], bins=n_bins)
binned_data = impl_data.groupby(gas_bins).agg({
    'gas_used': 'mean',
    'block_gossip_time': ['mean', 'count']
})

# Only plot bins with enough data
valid_bins = binned_data[binned_data[('block_gossip_time', 'count')] >= 5]
```

### 3.7 Statistical Summary Generation

**Cross-Period Comparison:**
```python
period_metrics = all_data.groupby('period').agg({
    'gas_used': ['mean', 'median', lambda x: np.percentile(x, 95)],
    'block_gossip_time': ['mean', 'median', lambda x: np.percentile(x, 95)],
    'slot': 'count'
})
```

**Head Time vs Block Gossip Analysis:**
```python
# Direction statistics
positive_diff = (all_data['time_difference'] > 0).sum()
negative_diff = (all_data['time_difference'] < 0).sum()
zero_diff = (all_data['time_difference'] == 0).sum()

print(f"Head > Gossip: {positive_diff:,} samples ({positive_diff/len(all_data)*100:.1f}%)")
```

## 4. Key Analysis Components

### 4.1 Correlation Analysis

The notebook calculates correlation coefficients between:
- Gas usage ↔ Block gossip time
- Gas usage ↔ Head time  
- Block gossip time ↔ Head time

### 4.2 Performance Metrics

**Primary Metrics:**
- Mean, median, and P95 values for all timing measurements
- Sample counts per consensus implementation
- Geographic distribution analysis (by continent)

**Derived Metrics:**
- Time differences between head time and block gossip time
- Trend line slopes and R-squared values
- Performance rankings by consensus implementation

### 4.3 Temporal Analysis

**Time Bucketing:** 30 equal-duration windows across each analysis period
**Trend Detection:** Linear regression analysis within each time bucket
**Cross-Period Comparison:** Statistical comparison between different time periods

## 5. Output and Results

### 5.1 Visualizations Generated

1. **Scatter Plots:** Gas usage vs arrival times (with trend lines and correlations)
2. **Time Series:** Dual-axis plots showing gas usage and arrival times over time buckets
3. **Heatmaps:** 2D density plots of gas usage vs arrival times
4. **Box Plots:** Distribution analysis across gas usage ranges
5. **Bar Charts:** Consensus implementation performance comparisons
6. **Correlation Plots:** Time bucket correlation analysis

### 5.2 Statistical Summaries

1. **Overall Metrics:** Comprehensive statistics per analysis period
2. **Implementation Rankings:** Performance ordered by P95 metrics
3. **Geographic Analysis:** Performance by continent
4. **Time Difference Analysis:** Head time vs block gossip time relationships

### 5.3 Insights Derived

The analysis reveals:
- Correlation strength between gas usage and propagation times
- Performance differences between consensus implementations
- Geographic variations in block propagation
- Temporal patterns in network performance
- Relationship between different timing metrics (head time vs block gossip time)

## Technical Dependencies

- **pandas:** Data manipulation and analysis
- **numpy:** Numerical computations and statistics
- **matplotlib/seaborn:** Data visualization
- **sqlalchemy:** Database connectivity
- **scipy:** Statistical analysis (linear regression)
- **python-dotenv:** Environment variable management

This analysis framework provides a comprehensive view of how gas usage impacts block propagation performance across different consensus implementations, geographic regions, and time periods in Ethereum networks.