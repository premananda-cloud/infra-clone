# Unsupervised clustering to identify urban typologies
from sklearn.cluster import KMeans
import umap

# Extract embedding vectors
X = np.array([b['embedding'] for b in building_embeddings])

# Cluster to find building types (residential, commercial, industrial, etc.)
kmeans = KMeans(n_clusters=5, random_state=42)
clusters = kmeans.fit_predict(X)

# Add clusters back to your data
gdf['urban_type'] = clusters

# For each cluster, characterize its properties
cluster_profiles = []
for i in range(5):
    cluster_data = gdf[gdf['urban_type'] == i]
    profile = {
        'cluster_id': i,
        'count': len(cluster_data),
        'avg_height': cluster_data['height'].mean(),
        'building_types': cluster_data['building_type'].value_counts().to_dict()
    }
    cluster_profiles.append(profile)

# Visualize embeddings in 2D to understand relationships
reducer = umap.UMAP()
embedding_2d = reducer.fit_transform(X)

# This tells you: areas with similar embeddings should be generated similarly!