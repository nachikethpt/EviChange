import rasterio
import numpy as np

def load_bands(folder, bands=["B04", "B03", "B02"]):
    """Load and stack specified Sentinel-2 bands from a folder."""
    arrays = []
    for b in bands:
        with rasterio.open(f"{folder}/{b}.tif") as src:
            arrays.append(src.read(1))
    return np.stack(arrays, axis=-1)

if __name__ == "__main__":
    print("load_data.py is working — rasterio imported successfully.")