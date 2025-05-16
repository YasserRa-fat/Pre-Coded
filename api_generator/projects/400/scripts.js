
// SCRIPTS
$(document).ready(function () {
    AOS.init();
});
var swiper = new Swiper('.swiper-container', {
    loop: true,
    autoplay: { delay: 2500, disableOnInteraction: false, },
    slidesPerView: 'auto',
    pagination: { el: '.swiper-pagination', clickable: true, },
    navigation: { nextEl: '.swiper-button-next', prevEl: '.swiper-button-prev', },
});
