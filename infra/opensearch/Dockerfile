# OpenSearch with Korean language support (Nori analyzer)
FROM opensearchproject/opensearch:2.11.1

# Install Nori plugin for Korean morphological analysis
# This enables proper tokenization of Korean text for BM25 search
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch analysis-nori

# Verify installation
RUN /usr/share/opensearch/bin/opensearch-plugin list | grep analysis-nori
