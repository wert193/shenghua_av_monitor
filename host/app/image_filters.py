import cv2
import numpy as np

ARM_IMPLEMENTATION = 'shared-opencv-v1'

def benchmark_frame():
    """Identical lossless input for image/video microbenchmarks."""
    return np.random.default_rng(42).integers(0,256,(180,320,3),dtype=np.uint8)

def arm_filter(bgr, mode):
    """Shared production ARM path for images, video and their benchmarks."""
    if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError('Expected uint8 BGR image with three channels')
    if bgr.shape[:2] == (1,1):return filter_frame(bgr,mode)
    if mode == 'smooth':
        return cv2.GaussianBlur(bgr,(3,3),0,borderType=cv2.BORDER_REPLICATE)
    if mode == 'sharpen':
        return cv2.filter2D(bgr,-1,np.array([[0,-1,0],[-1,5,-1],[0,-1,0]],np.float32),borderType=cv2.BORDER_REPLICATE)
    return filter_frame(bgr,mode)

def filter_frame(bgr, mode):
    if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError('Expected uint8 BGR image with three channels')
    # OpenCV 4.5.4 on PYNQ rejects some 1x1 filter2D matrices. Replicated
    # borders make this case exact: identity for unit-sum kernels, zero Sobel.
    if bgr.shape[:2] == (1, 1):
        if mode == 'edge':
            return np.zeros_like(bgr)
        if mode in ('original', 'smooth', 'sharpen'):
            return bgr.copy()
    border = cv2.BORDER_REPLICATE
    if mode == 'original':
        return bgr.copy()
    if mode == 'smooth':
        kernel = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32)
        total = cv2.filter2D(bgr, cv2.CV_16S, kernel, borderType=border)
        return ((total + 8) // 16).astype(np.uint8)
    if mode == 'edge':
        p = bgr.astype(np.int32)
        gray = (29 * p[:, :, 0] + 150 * p[:, :, 1] + 77 * p[:, :, 2] + 128 >> 8).astype(np.uint8)
        gx = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3, borderType=border)
        gy = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=3, borderType=border)
        edge = np.clip((np.abs(gx) + np.abs(gy) + 2) // 4, 0, 255).astype(np.uint8)
        return cv2.cvtColor(edge, cv2.COLOR_GRAY2BGR)
    if mode == 'sharpen':
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], np.float32)
        total = cv2.filter2D(bgr, cv2.CV_16S, kernel, borderType=border)
        return np.clip(total, 0, 255).astype(np.uint8)
    raise ValueError('Unknown filter: ' + mode)

def test_image():
    img = np.full((360, 640, 3), 45, dtype=np.uint8)
    cv2.rectangle(img, (40, 60), (230, 240), (70, 180, 230), -1)
    cv2.circle(img, (420, 150), 85, (190, 100, 40), -1)
    cv2.line(img, (30, 300), (600, 260), (240, 240, 240), 3)
    cv2.putText(img, 'PYNQ ARM', (260, 325), cv2.FONT_HERSHEY_SIMPLEX, 1, (220, 220, 220), 2)
    noise = np.random.default_rng(42).normal(0, 9, img.shape)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
