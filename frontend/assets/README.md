# Frontend assets — category placeholder images

Drop product-image **fallback placeholders** here. When a product's real
`image_url` can't be loaded, the card shows the placeholder for its category
(see `frontend/components/placeholders.py`).

Expected filenames (JPG or any format Streamlit's `st.image` accepts):

| Category (from the API) | Placeholder file |
|-------------------------|------------------|
| Shoes | `shoe-placeholder.jpg` |
| Clothing / Sportswear / Shirts | `shirt-placeholder.jpg` |
| Dresses | `dress-placeholder.jpg` |
| Accessories / Watches | `watch-placeholder.jpg` |
| Bags | `bag-placeholder.jpg` |
| _anything else_ | `product-placeholder.jpg` |

These files are **optional**: if a placeholder file is absent, the frontend
generates a simple labelled placeholder in-memory (Pillow), so the fallback
always works. Add the real images here to override the generated ones.

Recommended size: square, ~600×600 px.
