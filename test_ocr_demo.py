import streamlit as st
import pandas as pd
import numpy as np
import copy
import requests
import os

# file processing packages
import base64
from pdf2image import convert_from_path, convert_from_bytes
from PyPDF2 import PdfFileReader
import tempfile

# ocr packages
from PIL import Image
import pytesseract
import cv2

# ocr evaluation packages
from pdf import improvingOCR # for evaluation
from dinglehop.word_error_rate import *
from dinglehop.character_error_rate import *
from lang_confidence.lang_id import *
from nltk.corpus import words
import nltk
nltk.download('words')

#import enchant
#from spellchecker import SpellChecker (incompatible with python version 3)


# site copy
MAIN_TITLE_TEXT = 'Interactive OCR Evaluation\n'
TITLE_DESCRIPTION = '*Built for http://history-lab.org/*\n'
THRESHOLD_HELP = "If the pixel value is smaller than this number, it is set to 0"
MAXTHRESHOLD_HELP = "If the pixel value is larger than the threshold, it is set to this number"
PSM_HELP = "Set Tesseract to assume a certain form of image. See resources for more info"
OEM_HELP = "0 = Original Tesseract only.\n\
	    1 = Neural nets LSTM only.\n\
	    2 = Tesseract + LSTM.\n\
	    3 = Default, based on what is available."
DENOISE_HELP = "" # TODO

THRESHOLDING_METHODS = ["None", "Simple"] # ["None", "Simple", "Adaptive", "Otsu"]
DENOISING_METHODS = ["None", "Denoise", "Dilation", "Erosion"]
DET_ARCHS = ['Tesseract', 'Other OCR Method to test', 'EasyOCR']
DEFAULT_URL = "http://source.history-lab.org/pdb/source/pdf/DOC_0005996001.pdf"
COMPARE_HELP="Suppy a URL to a PDF given by the FOIArchive API"

def main():
	# Wide mode
	st.set_page_config(layout="centered")
	st.title(MAIN_TITLE_TEXT)
	st.write(TITLE_DESCRIPTION)

	# File selection UI
	start, end, uploaded_file = render_file_select_sidebar()
	
	st.sidebar.title("Preprocessing Methods")
	thresh_method = st.sidebar.radio("Thresholding Method", THRESHOLDING_METHODS)
	if thresh_method == "Simple" or thresh_method == "None": # TODO: diff logic
		thresh_val = st.sidebar.slider("Threshold Value", value=127, min_value=50, max_value=300, help=THRESHOLD_HELP)
		max_val = st.sidebar.slider("Maximum Value", value=255, min_value=100, max_value=1000, help=MAXTHRESHOLD_HELP)
	denoise_selection = st.sidebar.radio("Denoising Methods", DENOISING_METHODS)


	st.sidebar.title("Tesseract Parameters")
	st.sidebar.markdown("Have no idea what these options *actually* mean? See [Resources](#resources)", unsafe_allow_html=True)
	psm = st.sidebar.slider("Page Segmentation Mode", 0, 13, value=1, help=PSM_HELP)
	oem = st.sidebar.slider("OCR Engine Mode", 0, 3, value=1, help=OEM_HELP)
	tess_config = get_tess_config(psm, oem)

	if uploaded_file is None or start == "" or end == "":
		render_landing_layout()

	else: # use uploaded a file
		main_col1, main_col2 = st.columns(2)
		main_col1.subheader("Uploaded File")
		
		with main_col1.expander("File", expanded=True):
			images = get_images_from_upload(uploaded_file, start, end)
			st.image(images)
		

		# attempt to extract text
		main_col2.subheader("Preprocessed Image")
		with main_col2.expander("Preprocessing Results", expanded=True):
			if thresh_method == "Simple":
				imgs = grayscale_images(start, end, images, thresh_val, max_val)
			elif thresh_method == "None":
				imgs = no_threshold_images(start, end, images)
			imgs = PIL_to_np(start, end, imgs)
			imgs = denoise_images(start, end, imgs, denoise_selection)
			st.image(imgs)

		st.markdown("---")

		st.subheader("Text Extraction")
		st.write("*Runs Tesseract with the specified parameters*")
		
		with st.expander("Text from Pre-Processed Image", expanded=False):

			# refactor later
			extracted_text = ""
			for page_idx in range(start-1, end):
				extracted_text += pytesseract.image_to_string(imgs[page_idx], config=tess_config, lang="eng")
				if extracted_text == "":
					st.info("No Tesseract output :( Try tweaking more parameters!")
					break
				else:
					st.write(extracted_text)
			st.write('\n')
		st.download_button("Download OCR'd Text", extracted_text, file_name="ocr_results.txt")
		
		st.markdown("---")
		st.subheader("OCR Text Quality")
		st.write("*There is no standard consensus of how OCR quality should be measured. Below are a few metrics that approximate the quality of OCR. Expand each section to learn more about the metric.*")

		with st.expander("Garbageness Score", expanded=True):
			st.write("Approximates OCR quality via a \"garbageness\" score. **What percent of the total words are garbage?**")
			st.write("Derived from Wudtke et. al, [*Recognizing Garbage in OCR Output on Historical Documents*](https://dl.acm.org/doi/pdf/10.1145/2034617.2034626)")

			# save the tesseract output to a txt file
			text_file = open("ocr_text.txt", "w")
			text_file.write(extracted_text)
			text_file.close()
			summary_df, garbage_df = improvingOCR.garbageDetector("ocr_text.txt")
			st.write("**OCR Quality Summary:**")
			st.dataframe(summary_df)

			st.write("**Garbage Words:**")
			st.dataframe(garbage_df)
		
		st.write("\n\n")

		with st.expander("Language Confidence", expanded=True):
			st.write("Approximates OCR quality via a Language Confidence score as measured by [langid](https://github.com/saffsd/langid.py/tree/master/langid). **How confident are we that the result of the OCR output is in English?**")
			st.write("Derived from Baumann's [*Automatic evaluation of OCR quality*](https://ryanfb.github.io/etc/2015/03/16/automatic_evaluation_of_ocr_quality.html)")

			if os.path.exists("./ocr_text.txt"): 
				confidence = getConf().decode()
				st.write("Language Confidence (en): " + str(confidence))

			else:
				st.write("Waiting for Tesseract...")
		
		st.write("\n\n")

		with st.expander("Mean Word Confidence", expanded=True):
			st.write("Approximates OCR quality via a mean word confidence score as measured by [pytesseract](https://pypi.org/project/pytesseract/#:~:text=%23%20Get%20verbose%20data%20including%20boxes%2C%20confidences%2C%20line%20and%20page%20numbers%0Aprint(pytesseract.image_to_data(Image.open(%27test.png%27)))). **How confident is the OCR Engine that the word is this word?**")
			st.write("Modified from Springmann et. al's [*Automatic quality evaluation and (semi-) automatic improvement of OCR models for historical printings*](https://arxiv.org/abs/1606.05157)")

			# refactor later
			result_df = pd.DataFrame()
			for page_idx in range(start-1, end):
				text1 = pytesseract.image_to_data(imgs[page_idx], config=tess_config, lang="eng", output_type='data.frame')
				text_data = text1[text1.conf != -1] # remove all rows with no confidence values
				result_df = result_df.append(text_data[['conf', 'text']])
			
			st.write("\n\n")
			st.write("Mean word confidence: " + str(result_df['conf'].mean()))
			st.dataframe(result_df)
			# TODO: control flow for no tesseract output
		
		st.write("\n\n")

		with st.expander("Simple Dictionary Checking", expanded=True):
			st.write("Approximates OCR quality via dictionary checking. The [enchant dictionary](https://pyenchant.github.io/pyenchant/tutorial.html) is used. **What percent of the total words are in the dictionary?**")
			st.write("Derived from Alex et. al's Simple Quality Score in [*Estimating and Rating the Quality of Optically Character Recognised Text*](https://dl.acm.org/doi/pdf/10.1145/2595188.2595214?casa_token=j0lV_LEjZHMAAAAA:_Bntc_y9aMmc7pbYUSVlEIPtrqC_ZyP5x0w9WsOpqTUdtjv9bTaDYNM1PT3oe0Oj--g8l7aKXG8dMw)")

			st.write("\n\n")
			# TODO: resolve enchant issues. pyspellchecker is ok for now
			#spell = SpellChecker()
			#d = enchant.Dict("en_US")
			W_good = 0
			W_all = 1 # initialize to 1 to avoid dividing by 0

			# TODO: refactor
			misspelled_list = []
			count = 0
			for word in extracted_text.split():
				count +=1
				W_all +=1
				if word.isspace(): # skip whitespace
					continue
				#if spell[word]:
				#if d.check(word):
				if word in words.words() or word.isnumeric():
					W_good +=1
				else:
					misspelled_list.append(word)
			misspelled_df = pd.Series(misspelled_list).to_frame()
			score = 1 - (W_good / W_all)

			st.write("Simple Quality Score: " + str(score))
			st.write("Word Count: " + str(count))
			st.write("Num Misspelled Words: " + str(W_good))
			st.write("Misspelled Words: ")
			st.dataframe(misspelled_df)
			
		
		st.write("\n\n")

		with st.expander("Word and Character Error Rates", expanded=True):
			st.write("Approximates OCR quality via word error rate (WER) and character error rate (CER) calculated by comparing against Ground Truth data.")
			st.write("Derived from The Quator Project's open-source tool, [*dinglehopper*](https://github.com/qurator-spk/dinglehopper).")

			gt_text = st.file_uploader("Upload Ground Truth Text File",type=['txt'])
			st.write("\n\n")
			if gt_text is not None:
				gt_str = gt_text.read().decode()
				wer, n_words = word_error_rate_n(gt_str, extracted_text)
				cer, nc_words = character_error_rate_n(gt_str, extracted_text)
				#gt_words = words_normalized(extracted_text)
				#ocr_words = words_normalized(extracted_text)
				
				st.write("**Word and Character Error Rates Summary:**")
				st.write("WER: " + str(wer))
				st.write("CER: " + str(cer))
				st.write("word count: " + str(n_words))
				st.write("character count: " + str(nc_words))
				#st.write("gt_words: " + str(gt_words))
				#st.write("ocr_words: " + str(ocr_words))
		
		st.write("\n\n")

		st.markdown("---")

		st.subheader("OCR Quality - Internal Testing")
		st.write("**Comparison to FOIArchive Quality**")
		st.write("*Calculates the garbageness score of a body text from the FOIArchive*")
		source_url = st.text_input("URL to FOIArchive PDF", value=DEFAULT_URL, help=COMPARE_HELP)
		
		with st.expander("Comparison to FOIArchive Docs", expanded=True):
			body_text_file = get_FOI_text(source_url)
			

			summary_df, garbage_df = improvingOCR.garbageDetector("ocr_foi_text.txt")
			st.write("OCR Quality Summary")
			st.dataframe(summary_df)
			st.write("Garbage Words:")
			st.dataframe(garbage_df)
			
		
		st.markdown("---")

		# TODO: render resources refactor
		st.subheader("Resources")
		st.write("[Tesseract Page Segmentation Modes Explained](https://pyimagesearch.com/2021/11/15/tesseract-page-segmentation-modes-psms-explained-how-to-improve-your-ocr-accuracy/)")
		st.write("[Denoising Methods: Erosion, Dilation, Opening, Closing](https://docs.opencv.org/3.4/d9/d61/tutorial_py_morphological_ops.html)")


	# For newline
	st.sidebar.write('\n')


def get_FOI_text(source_url):
	URL = "https://api.foiarchive.org/docs"
	PARAMS = {"source": "eq." + source_url}

	# send GET request
	r = requests.get(url = URL, params = PARAMS)

	# format in json
	body_text = r.json()[0]['body']

	# write to file - TODO: make this a tmp file
	text_file = open("ocr_foi_text.txt", "w")
	text_file.write(body_text)
	text_file.close()
	return text_file

def is_range_valid(first: int, last: int, max_range: int):
	"""
	Helper For Page Range Input Errors
	"""
	if last - first < max_range:
		return True
	return False

def count_num_pages(file):
	"""
	Return number of pages in a pdf
	"""
	pdfReader = PdfFileReader(file)
	return pdfReader.numPages

def get_images_from_upload(file, start: int, end: int):
	"""
	Return PIL images from uploaded file
	"""
	tfile = tempfile.NamedTemporaryFile(delete=False)
	tfile.write(file.read())

	images = convert_from_path(tfile.name, first_page=start, last_page=end)
	return images

def get_tess_config(psm: int, oem: int):
	"""
	Returns formatted config for Tesseract
	"""
	# tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyz, 0123456789.%
	tess_config = "--psm " + str(psm)+ \
		" --oem " + str(oem) + \
		" -c " + \
		"preserve_interword_spaces=1"
	return tess_config

def grayscale_images(start, end, images, thresh_val, max_val):
	"""
	Returns PIL grayscaled images in start-end range
	"""
	imgs = []
	for page_idx in range(start-1, end):
		img = cv2.cvtColor(np.array(images[page_idx]), cv2.COLOR_BGR2GRAY)
		ret, img = cv2.threshold(img, thresh_val, max_val, cv2.THRESH_BINARY)
		img = Image.fromarray(img.astype(np.uint8))
		imgs.append(img)
	
	return imgs

def no_threshold_images(start, end, images):
	"""
	Returns PIL unmodified images in start-end range
	"""
	imgs = []
	for page_idx in range(start-1, end):
		img = cv2.cvtColor(np.array(images[page_idx]), cv2.COLOR_BGR2GRAY)
		img = Image.fromarray(img.astype(np.uint8))
		imgs.append(img)
	
	return imgs

def denoise_image(img, denoise_method):
	"""
	Returns image with specified denoising method applied
	"""
	kernel = np.ones((1, 1), np.uint8)
	if denoise_method == "None":
		pass
	elif denoise_method == "Denoise":
		img = remove_noise(img)
	elif denoise_method == "Erosion":
		img = thin_font(img)
	elif denoise_method == "Dilation":
		img = thick_font(img)
	
	return img

def thin_font(image):
	"""
	Applying Erosion
	"""
	image = cv2.bitwise_not(image)
	kernel = np.ones((2, 2), np.uint8)
	image = cv2.erode(image, kernel, iterations=1)
	image = cv2.bitwise_not(image)
	return image

def thick_font(image):
	"""
	Applying Dilation
	"""
	image = cv2.bitwise_not(image)
	kernel = np.ones((2, 2), np.uint8)
	image = cv2.dilate(image, kernel, iterations=1)
	image = cv2.bitwise_not(image)
	return image

def remove_noise(image):
	"""
	Removes noise from one image (closing denoising method)
	"""
	kernel = np.ones((1, 1), np.uint8)
	image = cv2.dilate(image, kernel, iterations=1)
	kernel = np.ones((1, 1), np.uint8)
	image = cv2.erode(image, kernel, iterations=1)
	image = cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)
	image = cv2.medianBlur(image, 3)
	return image

def denoise_images(start, end, images, denoise_method):
	"""
	Denoises a series of images
	"""
	imgs = []
	for page_idx in range(start-1, end):
		img = denoise_image(images[page_idx], denoise_method)
		imgs.append(img)
	
	return imgs

def PIL_to_np(start, end, pils):
	"""
	converts PIL objects to np arrays for cv2 to use
	"""
	imgs = []
	for page_idx in range(start-1, end):
		img = np.array(pils[page_idx])
		imgs.append(img)

	return imgs

def render_landing_layout():
	st.info('Please upload a file and select a range')
	st.subheader("Text Extracted")
	st.info('Please Upload a file and select a range')
	st.subheader("Resources")
	st.write("[Tesseract Page Segmentation Modes Explained](https://pyimagesearch.com/2021/11/15/tesseract-page-segmentation-modes-psms-explained-how-to-improve-your-ocr-accuracy/)")
	st.write("[Denoising Methods: Erosion, Dilation, Opening, Closing](https://docs.opencv.org/3.4/d9/d61/tutorial_py_morphological_ops.html)")

def render_file_select_sidebar():
	st.sidebar.title("File Selection")
	uploaded_file = st.sidebar.file_uploader("Upload a PDF Containing Text",type=['pdf'])
	st.set_option('deprecation.showfileUploaderEncoding', False) # Disabling warning

	st.sidebar.subheader("Enter Page Range")
	col1, col2 = st.sidebar.columns(2)
	start = col1.text_input("First Page")
	end = col2.text_input("Last Page")

	if start != "" and end != "" and uploaded_file is not None:
		uploaded_file_copy = copy.copy(uploaded_file) # PyPDF2 malforms input pdf, need to copy
		start = int(start)
		end = int(end)
		if not is_range_valid(start, end, count_num_pages(uploaded_file_copy)):
			st.sidebar.error("Invalid page range")
	return (start, end, uploaded_file)

def render_preprocess_sidebar():
	st.sidebar.title("Pre-Processing Parameters")
	thresh_method = st.sidebar.radio("Thresholding Method", THRESHOLDING_METHODS)
	if thresh_method == "Simple":
		thresh_val = st.sidebar.slider("Threshold Value", value=127, min_value=50, max_value=300, help=THRESHOLD_HELP)
		max_val = st.sidebar.slider("Maximum Value", value=255, min_value=100, max_value=1000, help=MAXTHRESHOLD_HELP)
	denoise_selection = st.sidebar.radio("Denoising Methods", DENOISING_METHODS)
	return (thresh_val, max_val, denoise_selection)

if __name__ == '__main__':
    main()
